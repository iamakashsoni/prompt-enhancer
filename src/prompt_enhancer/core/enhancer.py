from __future__ import annotations

import random
import re
import time

from openai import OpenAI

from prompt_enhancer.core.logging import log
from prompt_enhancer.core.config import (
    DEFAULT_MODEL,
    NVIDIA_BASE_URL,
    is_api_enabled,
    load_config,
    resolve_api_endpoint,
)
from prompt_enhancer.core.prompts import MODE_LABELS, STRICT_RETRY_SUFFIX, SYSTEM_PROMPTS  # noqa: F401

MAX_SELECTION_CHARS = 8000
# Backward compatibility for tests/imports
MAX_INPUT_CHARS = MAX_SELECTION_CHARS

_client_cache: tuple[str, str, int, OpenAI] | None = None

_MODE_TEMPERATURE: dict[str, float] = {
    "enhance":      0.10,
    "professional": 0.00,
}

_HARD_ANSWER_MARKERS = (
    "pip install",
    "npm install",
    "yarn add",
    "pnpm add",
    "follow these steps",
    "here is how",
    "here's how",
    "you can do this by",
    "to implement this",
    "example code",
    "sample code",
)

_SOFT_ANSWER_MARKERS = (
    "step 1:",
    "step 1 ",
    "step one",
    "setup.py",
    "dockerfile",
    "docker compose",
    ".github/workflows",
    "virtual environment",
    "step-by-step guide",
    "github actions",
    "terraform",
    "helm chart",
    "kubernetes",
    "aws console",
    "azure portal",
    "google cloud",
    "solution:",
    "recommended approach:",
    "best approach:",
    "you should use",
    "i recommend",
)

_CODE_LINE = re.compile(
    r"^\s*(def |class |import |from \w+ import |function \w+\(|@\w+|console\.log)",
    re.M,
)

# Professional mode produces structured prompts (Role, Objective, Requirements, etc.)
# so the answer-checker should allow bullet/numbered lines in its output.
_STRUCTURED_MODES = frozenset({"professional"})


class EnhancementError(ValueError):
    """Expected failure shown in the tray; not logged to the journal."""


def _length_budget(original: str, mode: str) -> int:
    n = len(original)
    if mode == "professional":
        return max(int(n * 2.5), n + 500)
    if n >= 400:
        return max(int(n * 2.3), n + 500)
    if n >= 150:
        return max(int(n * 1.9), n + 300)
    return max(int(n * 1.6), n + 200)


def _answer_check(output: str, original: str, mode: str = "enhance") -> tuple[str, str] | None:
    if "```" in output:
        return "hard", "code block in output"

    lower = output.lower()
    orig_lower = original.lower()
    soft_hits: list[str] = []

    for marker in _HARD_ANSWER_MARKERS:
        if marker in lower and marker not in orig_lower:
            return "hard", f"tutorial marker ({marker!r})"

    if _CODE_LINE.search(output):
        orig_lines = len(_CODE_LINE.findall(original)) if original else 0
        new_lines = len(_CODE_LINE.findall(output)) - orig_lines
        if new_lines >= 2:
            return "hard", f"{new_lines} new code lines"
        if new_lines == 1:
            soft_hits.append("new code line")

    for marker in _SOFT_ANSWER_MARKERS:
        if marker in lower and marker not in orig_lower:
            soft_hits.append(f"marker {marker!r}")

    if ("we'll" in lower or "we will" in lower) and (
        "we'll" not in orig_lower and "we will" not in orig_lower
    ):
        soft_hits.append("implementation voice")

    if mode not in _STRUCTURED_MODES:
        bullet_delta = len(re.findall(r"^\s*[\*\-]\s", output, re.M)) - len(
            re.findall(r"^\s*[\*\-]\s", original, re.M)
        )
        if bullet_delta >= 4:
            soft_hits.append(f"{bullet_delta} new bullet lines")

        numbered_delta = len(re.findall(r"^\s*\d+\.\s", output, re.M)) - len(
            re.findall(r"^\s*\d+\.\s", original, re.M)
        )
        if numbered_delta >= 4:
            soft_hits.append(f"{numbered_delta} new numbered lines")

    budget = _length_budget(original, mode)
    if len(output) > budget:
        soft_hits.append(f"length {len(output)} > budget {budget}")

    if len(soft_hits) >= 2:
        return "soft", "; ".join(soft_hits)
    if len(soft_hits) == 1 and len(output) > budget:
        return "soft", soft_hits[0]
    return None


def capture_looks_corrupted(text: str) -> str | None:
    if "```" in text:
        return "Selection contains code blocks — highlight only your original draft."
    stale = _answer_check(text, "", "enhance")
    if stale and stale[0] == "hard":
        return "Selection looks like old AI/tutorial text — highlight only your draft."
    if len(text) > MAX_SELECTION_CHARS:
        return (
            f"Selection is too long ({len(text)} chars) — "
            f"highlight at most {MAX_SELECTION_CHARS} characters."
        )
    return None


def _max_output_tokens(text: str, mode: str) -> int:
    base = len(text)
    # Both modes use the same formula — professional needs more room for structure,
    # enhance needs room for rephrasing. Cap at 2048 to keep latency low on 8B models.
    cap = min(max(int(base * 2.3), 512), 2048)
    return cap


def _resolve_system_prompt(mode: str, config: dict) -> str:
    if mode in SYSTEM_PROMPTS:
        return SYSTEM_PROMPTS[mode]
    raise EnhancementError(
        f"Unknown enhancement mode: {mode!r}. "
        "Only 'enhance' and 'professional' are supported."
    )


def _resolve_model(mode: str, config: dict) -> str:
    """Pick the LLM model for this mode.

    Resolution order:
      1. config["mode_models"][mode]   — per-mode override (power-user opt-in)
      2. config["model"]               — global default
      3. DEFAULT_MODEL                 — hardcoded fallback
    """
    mode_models = config.get("mode_models") or {}
    if isinstance(mode_models, dict):
        per_mode = mode_models.get(mode)
        if per_mode and isinstance(per_mode, str) and per_mode.strip():
            return per_mode.strip()
    return config.get("model", DEFAULT_MODEL) or DEFAULT_MODEL


def all_mode_ids(config: dict) -> list[str]:
    return list(MODE_LABELS.keys())


def mode_display_name(mode_id: str, config: dict) -> str:
    if mode_id in MODE_LABELS:
        return MODE_LABELS[mode_id]
    return mode_id


def _get_client(api_key: str, base_url: str, timeout: int) -> OpenAI:
    """Build a cached OpenAI client.

    IMPORTANT: max_retries=0 disables the SDK's built-in retry loop.
    The OpenAI SDK defaults to max_retries=2 (3 total attempts) with
    exponential backoff. Combined with the enhancer's own _call() retry
    loop (range(2)) and a 30s timeout, that produced ~180s of hanging
    before the user saw any error — making it look like the hotkey was
    broken when in fact the API was just unreachable.

    With max_retries=0, a single timeout fails fast (~30s) and the
    enhancer's own retry handles the transient-error case.
    """
    global _client_cache
    if (
        _client_cache is not None
        and _client_cache[0] == api_key
        and _client_cache[1] == base_url
        and _client_cache[2] == timeout
    ):
        return _client_cache[3]
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=float(timeout),
        max_retries=0,
    )
    _client_cache = (api_key, base_url, timeout, client)
    return client


def _is_transient_api_error(exc: Exception) -> bool:
    """True only for server-side transient errors worth retrying.

    IMPORTANT: timeouts are NOT transient. A timeout means either (a) the
    network is broken (retrying won't help) or (b) the model is slow
    (retrying starts from scratch and wastes another 30-60s). Retrying a
    timeout doubled the failure time from ~30s to ~66s, making the user
    think the hotkey was broken.
    """
    msg = str(exc).lower()
    if "502" in msg or "503" in msg or "bad gateway" in msg or "service unavailable" in msg:
        return True
    return False


def _api_error_to_enhancement(exc: Exception) -> EnhancementError:
    msg = str(exc)
    lower = msg.lower()
    if "429" in msg or "too many requests" in lower:
        return EnhancementError("NVIDIA rate limit (429). Wait a minute and try again.")
    if "401" in msg or "unauthorized" in lower:
        return EnhancementError(
            "Authentication failed (401). Check your API key in Settings."
        )
    if "403" in msg or "forbidden" in lower:
        return EnhancementError(
            "Authorization failed (403). Regenerate your API key at build.nvidia.com."
        )
    if "404" in msg or "not found" in lower:
        return EnhancementError(
            f"Model not found. Pick {DEFAULT_MODEL!r} in Settings → AI Model."
        )
    if "timeout" in lower or "timed out" in lower:
        return EnhancementError(
            "Request timed out. Try again or increase timeout in Settings."
        )
    if "502" in msg or "503" in msg:
        return EnhancementError("NVIDIA service unavailable. Try again in a moment.")
    if "500" in msg or "internal server error" in lower:
        return EnhancementError("NVIDIA server error (5xx). Try again shortly.")
    return EnhancementError("Enhancement failed. Check logs or try again.")


def enhance_text(
    text: str,
    mode: str = "enhance",
    config: dict | None = None,
) -> str:
    if len(text) > MAX_SELECTION_CHARS:
        raise EnhancementError(
            f"Selection too long ({len(text)} chars). "
            f"Highlight at most {MAX_SELECTION_CHARS} characters."
        )

    config = config or load_config()
    if not is_api_enabled(config):
        raise EnhancementError(
            "Cloud enhancement is disabled (air-gap mode). "
            "Open Settings → API Provider to enable."
        )

    try:
        base_url, api_key = resolve_api_endpoint(config)
    except ValueError as exc:
        msg = str(exc)
        if msg == "missing api key":
            raise EnhancementError(
                "API key not configured.\n"
                "Right-click the tray icon → Settings to add your key."
            ) from exc
        raise EnhancementError(msg) from exc

    model: str = _resolve_model(mode, config)
    timeout: int = config.get("timeout", 30)
    system_prompt = _resolve_system_prompt(mode, config)
    temperature = _MODE_TEMPERATURE.get(mode, 0.0)
    max_tokens = _max_output_tokens(text, mode)

    client = _get_client(api_key, base_url, timeout)

    def _call(extra_system: str = "") -> str:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt + extra_system},
                        {
                            "role": "user",
                            "content": text,
                        },
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                result = completion.choices[0].message.content
                if not result:
                    raise EnhancementError("Received an empty response from NVIDIA NIM.")
                return result.strip()
            except EnhancementError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and _is_transient_api_error(exc):
                    time.sleep(random.uniform(0.3, 0.8))
                    continue
                raise _api_error_to_enhancement(exc) from exc
        raise _api_error_to_enhancement(last_exc) from last_exc  # type: ignore[arg-type]

    output = _call()
    check = _answer_check(output, text, mode)
    if check:
        severity, reason = check
        log(f"[Enhancer] {mode}: retrying ({severity}: {reason})")
        output = _call(STRICT_RETRY_SUFFIX)
        retry_check = _answer_check(output, text, mode)
        if retry_check:
            r_severity, r_reason = retry_check
            log(f"[Enhancer] {mode}: using output despite check ({r_severity}: {r_reason})")
        else:
            log(f"[Enhancer] {mode}: strict retry ok")
    return output


def test_connection(
    api_key: str,
    model: str,
    *,
    base_url: str = NVIDIA_BASE_URL,
) -> str:
    try:
        client = OpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url,
            timeout=15.0,
        )
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            temperature=0,
            max_tokens=10,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        msg = str(exc)
        if "404" in msg:
            raise ValueError(
                f"Model not found: {model!r}. "
                f"Pick {DEFAULT_MODEL!r} in Settings → AI Model, click Save, "
                f"then Test Connection again."
            ) from exc
        if "401" in msg or "Unauthorized" in msg:
            raise ValueError(
                "Authentication failed (401). Check your nvapi- key at build.nvidia.com."
            ) from exc
        if "403" in msg or "Forbidden" in msg:
            raise ValueError(
                "Authorization failed (403). Regenerate your API key at build.nvidia.com."
            ) from exc
        if "429" in msg or "Too Many Requests" in msg:
            raise ValueError(
                "Rate limit (429). Wait a minute before testing again."
            ) from exc
        raise ValueError(msg) from exc
