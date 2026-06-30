import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

import keyring
import keyring.errors

from prompts import MODE_LABELS

# In-memory cache — avoids hitting NVIDIA on every hotkey / load_config().
_CONFIG_CACHE: tuple[float, dict] | None = None
_MODEL_CACHE: tuple[float, list[str]] | None = None
_MODEL_CACHE_TTL_S = 86400  # 24 hours

CONFIG_VERSION = 1
CONFIG_DIR = Path.home() / ".prompt-enhancer"
CONFIG_FILE = CONFIG_DIR / "config.json"
WELCOME_DONE_FILE = CONFIG_DIR / ".welcome_done"
SERVICE_NAME = "prompt-enhancer"
API_KEY_USERNAME = "nvidia-api-key"
NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"

MAX_CUSTOM_PROMPT_CHARS = 4096
MAX_CUSTOM_BASE_URL_CHARS = 512

API_PROVIDER_NVIDIA = "nvidia"
API_PROVIDER_CUSTOM = "custom"
API_PROVIDER_DISABLED = "disabled"
API_PROVIDERS = (API_PROVIDER_NVIDIA, API_PROVIDER_CUSTOM, API_PROVIDER_DISABLED)

DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

CURATED_MODELS = [
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "mistralai/mistral-large-2-instruct",
]

OBSOLETE_MODELS = {
    "meta/llama-3.1-405b-instruct",
    "google/gemma-2-27b-it",
    "microsoft/phi-3-medium-128k-instruct",
}

DEFAULT_CONFIG: dict = {
    "config_version": CONFIG_VERSION,
    "api_provider": API_PROVIDER_NVIDIA,
    "custom_api_base_url": "",
    "model": DEFAULT_MODEL,
    "mode_models": {},
    "timeout": 30,
    "start_minimized": True,
    "hotkeys": {
        "enhance":      "<ctrl>+<alt>+e",
        "professional": "<ctrl>+<alt>+p",
        "shorten":      "<ctrl>+<alt>+s",
        "expand":       "<ctrl>+<alt>+x",
        "casual":       "<ctrl>+<alt>+c",
    },
    "custom_modes": {},
    "available_models": CURATED_MODELS.copy(),
}


def fetch_nvidia_models(timeout: float = 10.0) -> list[str]:
    with urllib.request.urlopen(NVIDIA_MODELS_URL, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m["id"] for m in data.get("data", [])]


def fetch_nvidia_models_cached(
    *,
    force_refresh: bool = False,
    timeout: float = 10.0,
) -> list[str] | None:
    global _MODEL_CACHE
    now = time.monotonic()
    if (
        not force_refresh
        and _MODEL_CACHE is not None
        and (now - _MODEL_CACHE[0]) < _MODEL_CACHE_TTL_S
    ):
        return _MODEL_CACHE[1]
    try:
        models = fetch_nvidia_models(timeout=timeout)
        _MODEL_CACHE = (now, models)
        return models
    except Exception:
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE[1]
        return None


def invalidate_model_cache() -> None:
    global _MODEL_CACHE
    _MODEL_CACHE = None


def models_for_settings(config: dict, *, force_refresh: bool = False) -> list[str]:
    try:
        live_list = fetch_nvidia_models_cached(force_refresh=force_refresh)
        if live_list is None:
            raise OSError("model catalog unavailable")
        live = set(live_list)
        options = [m for m in CURATED_MODELS if m in live]
    except Exception:
        options = [
            m for m in (config.get("available_models") or CURATED_MODELS)
            if m not in OBSOLETE_MODELS
        ]

    if not options:
        options = CURATED_MODELS.copy()

    current = config.get("model")
    if current and current not in OBSOLETE_MODELS and current not in options:
        options = [current] + options
    return options


def _secure_path(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _secure_path(CONFIG_DIR, 0o700)


def is_welcome_done() -> bool:
    return WELCOME_DONE_FILE.exists()


def mark_welcome_done() -> None:
    ensure_config_dir()
    WELCOME_DONE_FILE.touch()


def is_api_enabled(config: dict | None = None) -> bool:
    cfg = config or {}
    return cfg.get("api_provider", API_PROVIDER_NVIDIA) != API_PROVIDER_DISABLED


def validate_custom_base_url(url: str) -> str | None:
    url = (url or "").strip()
    if not url:
        return "Enter a base URL (e.g. http://localhost:11434/v1)."
    if "\x00" in url:
        return "Base URL cannot contain null bytes."
    if len(url) > MAX_CUSTOM_BASE_URL_CHARS:
        return f"Base URL exceeds {MAX_CUSTOM_BASE_URL_CHARS} characters."
    if not (url.startswith("https://") or url.startswith("http://")):
        return "Base URL must start with http:// or https://."
    return None


def resolve_api_endpoint(config: dict) -> tuple[str, str]:
    """Return (base_url, api_key) for OpenAI-compatible clients."""
    provider = config.get("api_provider", API_PROVIDER_NVIDIA)
    if provider == API_PROVIDER_DISABLED:
        raise ValueError("API disabled")
    if provider == API_PROVIDER_CUSTOM:
        base_url = config.get("custom_api_base_url", "").strip()
        err = validate_custom_base_url(base_url)
        if err:
            raise ValueError(err)
        api_key = get_api_key() or "not-needed"
        return base_url.rstrip("/"), api_key
    api_key = get_api_key()
    if not api_key:
        raise ValueError("missing api key")
    return NVIDIA_BASE_URL, api_key


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def validate_custom_prompt(prompt: str) -> str | None:
    if "\x00" in prompt:
        return "System prompt cannot contain null bytes."
    if len(prompt) > MAX_CUSTOM_PROMPT_CHARS:
        return f"System prompt exceeds {MAX_CUSTOM_PROMPT_CHARS} characters."
    return None


def sanitize_custom_modes(custom_modes: dict) -> dict:
    """Drop invalid custom modes; truncate nothing — reject on save instead."""
    cleaned: dict = {}
    for mode_id, info in custom_modes.items():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name", mode_id)).strip()
        prompt = str(info.get("system_prompt", "")).strip()
        if not name or not prompt:
            continue
        if validate_custom_prompt(prompt):
            continue
        cleaned[mode_id] = {"name": name, "system_prompt": prompt}
    return cleaned


def sanitize_mode_models(mode_models: dict) -> dict:
    """Drop invalid per-mode model overrides.

    Accepts {"mode_id": "model_name"} pairs. Drops non-dict input, non-string
    values, empty strings, and obsolete models. Returns a clean dict.
    """
    if not isinstance(mode_models, dict):
        return {}
    cleaned: dict = {}
    for mode_id, model in mode_models.items():
        if not isinstance(mode_id, str) or not isinstance(model, str):
            continue
        model = model.strip()
        if not model or model in OBSOLETE_MODELS:
            continue
        cleaned[mode_id] = model
    return cleaned


def _valid_mode_ids(config: dict) -> set[str]:
    return set(MODE_LABELS.keys()) | set(config.get("custom_modes", {}).keys())


def _prune_orphan_hotkeys(config: dict) -> dict:
    valid = _valid_mode_ids(config)
    hotkeys = config.get("hotkeys", {})
    pruned = {k: v for k, v in hotkeys.items() if k in valid and str(v).strip()}
    if pruned != hotkeys:
        config = {**config, "hotkeys": pruned}
    return config


def _normalize_config(config: dict) -> dict:
    merged = DEFAULT_CONFIG.copy()
    merged.update({k: v for k, v in config.items() if k != "hotkeys"})
    if "hotkeys" in config:
        merged["hotkeys"] = {**DEFAULT_CONFIG["hotkeys"], **config["hotkeys"]}
    if merged.get("config_version", 0) < CONFIG_VERSION:
        merged["config_version"] = CONFIG_VERSION
    provider = merged.get("api_provider", API_PROVIDER_NVIDIA)
    if provider not in API_PROVIDERS:
        provider = API_PROVIDER_NVIDIA
    merged["api_provider"] = provider
    merged["custom_api_base_url"] = str(merged.get("custom_api_base_url", "")).strip()
    merged["custom_modes"] = sanitize_custom_modes(merged.get("custom_modes", {}))
    merged["mode_models"] = sanitize_mode_models(merged.get("mode_models", {}))
    merged = _prune_orphan_hotkeys(merged)
    merged["available_models"] = models_for_settings(merged)
    return merged


def _migrate_config(config: dict) -> dict:
    changed = False
    if config.get("model") in OBSOLETE_MODELS:
        config = {**config, "model": DEFAULT_MODEL}
        changed = True
    if config.get("config_version", 0) < CONFIG_VERSION:
        config = {**config, "config_version": CONFIG_VERSION}
        changed = True
    pruned = _prune_orphan_hotkeys(config)
    if pruned.get("hotkeys") != config.get("hotkeys"):
        config = pruned
        changed = True
    options = models_for_settings(config)
    if config.get("available_models") != options:
        config = {**config, "available_models": options}
        changed = True
    if changed:
        save_config(config)
    return config


def invalidate_config_cache() -> None:
    """Force next load_config() to re-read from disk."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def _config_mtime() -> float | None:
    try:
        return CONFIG_FILE.stat().st_mtime
    except OSError:
        return None


def load_config() -> dict:
    global _CONFIG_CACHE
    ensure_config_dir()

    # Fast path: return cached config if the file hasn't changed on disk.
    # This avoids the file read + JSON parse + _normalize_config + _migrate_config
    # chain on every hotkey press (saves ~5-8ms per trigger).
    if _CONFIG_CACHE is not None:
        cached_mtime, cached_config = _CONFIG_CACHE
        current_mtime = _config_mtime()
        if current_mtime is not None and current_mtime == cached_mtime:
            return cached_config

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        cached = DEFAULT_CONFIG.copy()
        _CONFIG_CACHE = (_config_mtime() or 0.0, cached)
        return cached
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = _normalize_config(data)
    result = _migrate_config(merged)

    # Cache after migration so the mtime reflects any writes _migrate_config made.
    _CONFIG_CACHE = (_config_mtime() or 0.0, result)
    return result


def save_config(config: dict) -> None:
    global _CONFIG_CACHE
    ensure_config_dir()
    config = _normalize_config(config)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".config-", suffix=".tmp", dir=str(CONFIG_DIR), text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _secure_path(Path(tmp_path), 0o600)
        os.replace(tmp_path, CONFIG_FILE)
        _secure_path(CONFIG_FILE, 0o600)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    # Invalidate cache so next load_config() picks up the new file.
    _CONFIG_CACHE = None


def validate_api_key(key: str) -> str | None:
    key = (key or "").strip()
    if not key:
        return "Paste your NVIDIA API key (starts with nvapi-)."
    if not key.startswith("nvapi-"):
        return (
            "That does not look like an NVIDIA API key. "
            "Create one at build.nvidia.com — it should start with nvapi-."
        )
    if len(key) < 20:
        return "API key looks too short — copy the full key from build.nvidia.com."
    return None


_KEYRING_HINT = (
    "Could not access the OS keychain. On Linux install "
    "gnome-keyring or python3-secretstorage; then log in again."
)


def get_api_key() -> str | None:
    try:
        return keyring.get_password(SERVICE_NAME, API_KEY_USERNAME)
    except keyring.errors.KeyringError:
        return None
    except Exception:
        return None


def set_api_key(key: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, API_KEY_USERNAME, key)
    except keyring.errors.KeyringError as exc:
        raise RuntimeError(_KEYRING_HINT) from exc


def delete_api_key() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, API_KEY_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
