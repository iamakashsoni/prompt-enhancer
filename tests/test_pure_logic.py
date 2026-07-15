"""Pure-logic tests for prompt-enhancer — no GUI / display / network deps.

Run: pytest tests/ -v

These tests cover the functions most likely to silently regress. Each test
class maps to one module. If you change logic in any of these files, the
corresponding test class should catch regressions before CI ships a broken
release.

Covered:
- enhancer: _answer_check, _length_budget, _max_output_tokens,
  capture_looks_corrupted, mode_display_name, _resolve_system_prompt,
  _is_transient_api_error, _api_error_to_enhancement
- config: _normalize_config, _migrate_config, resolve_api_endpoint,
  fetch_ollama_models, validate_api_key, validate_custom_base_url,
  validate_custom_prompt, is_api_enabled, _prune_orphan_hotkeys
- updater: _parse_version, _version_lt, evaluate, _download_url
- evdev_hotkeys: _parse_pynput_combo
"""
from __future__ import annotations

import pytest

# After the Linux-only package refactor, modules live under the
# `prompt_enhancer` package. Alias them back to the bare names the tests
# were written against, so the test bodies don't need to change.
from prompt_enhancer.core import config
from prompt_enhancer.core import enhancer
from prompt_enhancer.core import updater
from prompt_enhancer.platform import evdev_hotkeys as linux_input


# ══════════════════════════════════════════════════════════════════════════════
#  enhancer._answer_check — the tutorial/code-dump detector
# ══════════════════════════════════════════════════════════════════════════════

class TestAnswerCheck:
    def test_clean_rewrite_passes(self):
        assert enhancer._answer_check("My clearer report.", "my report is bad", "enhance") is None

    def test_code_block_is_hard_fail(self):
        result = enhancer._answer_check("Here:\n```python\nprint('hi')\n```", "fix this", "enhance")
        assert result is not None and result[0] == "hard"

    def test_tutorial_marker_is_hard_fail(self):
        result = enhancer._answer_check("pip install foo then follow these steps", "how to install", "enhance")
        assert result is not None and result[0] == "hard"

    def test_soft_marker_alone_passes(self):
        assert enhancer._answer_check("Use kubernetes for this.", "deploy it", "enhance") is None

    def test_two_soft_markers_is_soft_fail(self):
        output = "step 1: do X. i recommend kubernetes."
        result = enhancer._answer_check(output, "do it", "enhance")
        assert result is not None and result[0] == "soft"

    def test_excessive_length_is_soft_fail(self):
        result = enhancer._answer_check("x" * 5000, "short", "enhance")
        assert result is not None and result[0] == "soft"

    def test_markers_in_original_are_not_flagged(self):
        original = "step 1: do X\nstep 2: do Y"
        output = "Step 1: Do X\nStep 2: Do Y"
        assert enhancer._answer_check(output, original, "enhance") is None


# ══════════════════════════════════════════════════════════════════════════════
#  enhancer._length_budget / _max_output_tokens
# ══════════════════════════════════════════════════════════════════════════════

class TestLengthBudget:
    def test_professional_budget_generous(self):
        """Professional mode produces structured prompts — needs room."""
        assert enhancer._length_budget("x" * 100, "professional") >= 250

    def test_small_enhance_floor(self):
        assert enhancer._length_budget("hi", "enhance") >= 202  # max(3, 202)


class TestMaxOutputTokens:
    def test_professional_cap_2048(self):
        assert enhancer._max_output_tokens("x" * 10000, "professional") == 2048

    def test_enhance_cap_2048(self):
        assert enhancer._max_output_tokens("x" * 10000, "enhance") == 2048


# ══════════════════════════════════════════════════════════════════════════════
#  enhancer.capture_looks_corrupted
# ══════════════════════════════════════════════════════════════════════════════

class TestCaptureLooksCorrupted:
    def test_clean_text_passes(self):
        assert enhancer.capture_looks_corrupted("my draft about cats") is None

    def test_code_block_rejected(self):
        msg = enhancer.capture_looks_corrupted("```\ncode\n```")
        assert msg and "code blocks" in msg

    def test_too_long_rejected(self):
        msg = enhancer.capture_looks_corrupted("x" * (enhancer.MAX_SELECTION_CHARS + 1))
        assert msg and "too long" in msg

    def test_tutorial_text_rejected(self):
        msg = enhancer.capture_looks_corrupted("pip install foo then follow these steps")
        assert msg is not None


# ══════════════════════════════════════════════════════════════════════════════
#  enhancer.mode_display_name / _resolve_system_prompt
# ══════════════════════════════════════════════════════════════════════════════

class TestModeResolution:
    def test_builtin_display_name(self):
        assert enhancer.mode_display_name("enhance", {}) == "Enhance"

    def test_professional_display_name(self):
        assert enhancer.mode_display_name("professional", {}) == "Professional"

    def test_unknown_falls_back_to_id(self):
        assert enhancer.mode_display_name("nonexistent", {}) == "nonexistent"

    def test_resolve_builtin_prompt(self):
        assert "STRICT RULES" in enhancer._resolve_system_prompt("enhance", {})

    def test_resolve_professional_prompt(self):
        prompt = enhancer._resolve_system_prompt("professional", {})
        assert "INTENT DETECTION" in prompt
        assert "PROMPT STRUCTURE" in prompt

    def test_resolve_unknown_mode_raises(self):
        with pytest.raises(enhancer.EnhancementError, match="Unknown enhancement mode"):
            enhancer._resolve_system_prompt("nope", {})


# ══════════════════════════════════════════════════════════════════════════════
#  enhancer._resolve_model — per-mode model override
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveModel:
    def test_no_config_returns_default(self):
        assert enhancer._resolve_model("enhance", {}) == config.DEFAULT_MODEL

    def test_global_model_used_when_no_override(self):
        cfg = {"model": "meta/llama-3.1-8b-instruct"}
        assert enhancer._resolve_model("enhance", cfg) == "meta/llama-3.1-8b-instruct"

    def test_per_mode_override_wins(self):
        cfg = {
            "model": "qwen/qwen2.5-7b-instruct",
            "mode_models": {"professional": "meta/llama-3.1-8b-instruct"},
        }
        assert enhancer._resolve_model("professional", cfg) == "meta/llama-3.1-8b-instruct"
        # Other modes still use global.
        assert enhancer._resolve_model("enhance", cfg) == "qwen/qwen2.5-7b-instruct"

    def test_override_for_unknown_mode_does_not_leak(self):
        cfg = {"mode_models": {"nonexistent": "meta/llama-3.1-8b-instruct"}}
        assert enhancer._resolve_model("enhance", cfg) == config.DEFAULT_MODEL

    def test_empty_override_string_falls_back(self):
        cfg = {"mode_models": {"enhance": "  "}}
        assert enhancer._resolve_model("enhance", cfg) == config.DEFAULT_MODEL

    def test_non_dict_mode_models_ignored(self):
        cfg = {"mode_models": "not a dict"}
        assert enhancer._resolve_model("enhance", cfg) == config.DEFAULT_MODEL

    def test_non_string_override_ignored(self):
        cfg = {"mode_models": {"enhance": 123}}
        assert enhancer._resolve_model("enhance", cfg) == config.DEFAULT_MODEL

    def test_global_model_empty_falls_back_to_default(self):
        cfg = {"model": ""}
        assert enhancer._resolve_model("enhance", cfg) == config.DEFAULT_MODEL


class TestSanitizeModeModels:
    def test_drops_non_dict(self):
        assert config.sanitize_mode_models("nope") == {}
        assert config.sanitize_mode_models(None) == {}
        assert config.sanitize_mode_models([]) == {}

    def test_drops_non_string_values(self):
        assert config.sanitize_mode_models({"enhance": 123, "professional": None}) == {}

    def test_drops_empty_strings(self):
        assert config.sanitize_mode_models({"enhance": "", "professional": "  "}) == {}

    def test_drops_obsolete_models(self):
        result = config.sanitize_mode_models({"enhance": "google/gemma-2-27b-it"})
        assert result == {}

    def test_keeps_valid(self):
        result = config.sanitize_mode_models({
            "enhance": "qwen/qwen2.5-7b-instruct",
            "professional": "meta/llama-3.1-8b-instruct",
        })
        assert result == {
            "enhance": "qwen/qwen2.5-7b-instruct",
            "professional": "meta/llama-3.1-8b-instruct",
        }

    def test_strips_whitespace(self):
        result = config.sanitize_mode_models({"enhance": "  meta/llama-3.1-8b-instruct  "})
        assert result == {"enhance": "meta/llama-3.1-8b-instruct"}

    def test_drops_non_string_keys(self):
        # JSON keys are always strings, but defensive: int keys shouldn't crash.
        assert config.sanitize_mode_models({1: "meta/llama-3.1-8b-instruct"}) == {}


class TestNormalizeWithModeModels:
    def test_mode_models_preserved_through_normalize(self, no_network):
        merged = config._normalize_config({
            "mode_models": {"professional": "meta/llama-3.1-8b-instruct"},
        })
        assert merged["mode_models"] == {"professional": "meta/llama-3.1-8b-instruct"}

    def test_mode_models_sanitized_through_normalize(self, no_network):
        merged = config._normalize_config({
            "mode_models": {"enhance": 123, "professional": "", "ok": "meta/llama-3.1-8b-instruct"},
        })
        assert merged["mode_models"] == {"ok": "meta/llama-3.1-8b-instruct"}

    def test_mode_models_defaults_to_empty(self, no_network):
        merged = config._normalize_config({})
        assert merged["mode_models"] == {}


# ══════════════════════════════════════════════════════════════════════════════
#  enhancer API error mapping
# ══════════════════════════════════════════════════════════════════════════════

class TestApiErrorMapping:
    def test_429_maps_to_rate_limit(self):
        assert "429" in str(enhancer._api_error_to_enhancement(Exception("HTTP 429 Too Many Requests")))

    def test_401_maps_to_auth(self):
        assert "401" in str(enhancer._api_error_to_enhancement(Exception("401 Unauthorized")))

    def test_404_maps_to_model_not_found(self):
        assert "Model not found" in str(enhancer._api_error_to_enhancement(Exception("404 Not Found")))

    def test_transient_detection(self):
        # Timeouts are NOT transient — retrying a slow model just wastes another 30-90s.
        assert not enhancer._is_transient_api_error(Exception("connection timeout"))
        assert enhancer._is_transient_api_error(Exception("503 service unavailable"))
        assert not enhancer._is_transient_api_error(Exception("401 unauthorized"))


# ══════════════════════════════════════════════════════════════════════════════
#  config._normalize_config / _migrate_config
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def no_network(monkeypatch):
    """Stub NVIDIA model fetch so config logic is deterministic offline."""
    monkeypatch.setattr(config, "fetch_nvidia_models_cached", lambda **k: ["qwen/qwen2.5-7b-instruct"])


class TestNormalizeConfig:
    def test_empty_dict_gets_defaults(self, no_network):
        merged = config._normalize_config({})
        assert merged["api_provider"] == config.API_PROVIDER_NVIDIA
        assert merged["model"] == config.DEFAULT_MODEL
        assert "enhance" in merged["hotkeys"]

    def test_invalid_provider_falls_back_to_nvidia(self, no_network):
        merged = config._normalize_config({"api_provider": "bogus"})
        assert merged["api_provider"] == config.API_PROVIDER_NVIDIA

    def test_orphan_hotkeys_are_pruned(self, no_network):
        merged = config._normalize_config({
            "hotkeys": {
                "enhance": "<ctrl>+<alt>+e",
                "deleted_mode": "<ctrl>+<alt>+z",
            }
        })
        assert "deleted_mode" not in merged["hotkeys"]
        assert "enhance" in merged["hotkeys"]


class TestMigrateConfig:
    def test_obsolete_model_is_migrated(self, monkeypatch, no_network):
        monkeypatch.setattr(config, "save_config", lambda c: None)
        migrated = config._migrate_config({"model": "google/gemma-2-27b-it", "config_version": 1})
        assert migrated["model"] == config.DEFAULT_MODEL

    def test_70b_model_is_migrated(self, monkeypatch, no_network):
        """70B models were removed for being too slow — must auto-migrate."""
        monkeypatch.setattr(config, "save_config", lambda c: None)
        for old_model in (
            "meta/llama-3.3-70b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct",
            "mistralai/mistral-large-2-instruct",
        ):
            migrated = config._migrate_config({"model": old_model, "config_version": 1})
            assert migrated["model"] == config.DEFAULT_MODEL, f"{old_model} not migrated"

    def test_current_model_is_kept(self, monkeypatch, no_network):
        monkeypatch.setattr(config, "save_config", lambda c: None)
        migrated = config._migrate_config({"model": config.DEFAULT_MODEL, "config_version": 1})
        assert migrated["model"] == config.DEFAULT_MODEL

    def test_qwen_model_is_kept(self, monkeypatch, no_network):
        """New curated model qwen2.5-7b should NOT be migrated."""
        monkeypatch.setattr(config, "save_config", lambda c: None)
        migrated = config._migrate_config({"model": "qwen/qwen2.5-7b-instruct", "config_version": 1})
        assert migrated["model"] == "qwen/qwen2.5-7b-instruct"


# ══════════════════════════════════════════════════════════════════════════════
#  config.load_config cache (performance optimization)
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigCache:
    def test_invalidate_clears_cache(self):
        config._CONFIG_CACHE = (12345.0, {"dummy": True})
        config.invalidate_config_cache()
        assert config._CONFIG_CACHE is None

    def test_save_config_invalidates_cache(self, monkeypatch, tmp_path, no_network):
        # Point CONFIG_FILE at a tmp path so we don't touch the real user config.
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config._CONFIG_CACHE = (12345.0, {"dummy": True})
        config.save_config(config.DEFAULT_CONFIG)
        assert config._CONFIG_CACHE is None

    def test_repeated_load_uses_cache_on_unchanged_file(self, monkeypatch, tmp_path, no_network):
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
        config.invalidate_config_cache()
        # First load reads from disk (creates default since file missing).
        cfg1 = config.load_config()
        assert config._CONFIG_CACHE is not None
        cached_mtime = config._CONFIG_CACHE[0]
        # Second load should hit cache (same mtime) — same dict object returned.
        cfg2 = config.load_config()
        assert cfg2 is cfg1
        assert config._CONFIG_CACHE[0] == cached_mtime


# ══════════════════════════════════════════════════════════════════════════════
#  config validators
# ══════════════════════════════════════════════════════════════════════════════

class TestValidators:
    def test_api_key_empty(self):
        assert config.validate_api_key("") is not None

    def test_api_key_wrong_prefix(self):
        assert config.validate_api_key("sk-abc123") is not None

    def test_api_key_too_short(self):
        assert config.validate_api_key("nvapi-x") is not None

    def test_api_key_valid(self):
        assert config.validate_api_key("nvapi-" + "a" * 30) is None

    def test_base_url_empty(self):
        assert config.validate_custom_base_url("") is not None

    def test_base_url_wrong_scheme(self):
        assert config.validate_custom_base_url("ftp://x") is not None

    def test_base_url_valid_http(self):
        assert config.validate_custom_base_url("http://localhost:11434/v1") is None

    def test_base_url_valid_https(self):
        assert config.validate_custom_base_url("https://api.example.com/v1") is None

    def test_base_url_null_byte(self):
        assert config.validate_custom_base_url("http://x\x00") is not None

    def test_prompt_null_byte(self):
        assert config.validate_custom_prompt("hello\x00world") is not None

    def test_prompt_too_long(self):
        assert config.validate_custom_prompt("x" * (config.MAX_CUSTOM_PROMPT_CHARS + 1)) is not None

    def test_prompt_valid(self):
        assert config.validate_custom_prompt("Be nice.") is None


# ══════════════════════════════════════════════════════════════════════════════
#  config.is_api_enabled / Ollama provider / model fetch
# ══════════════════════════════════════════════════════════════════════════════

class TestApiEnabled:
    def test_nvidia_enabled(self):
        assert config.is_api_enabled({"api_provider": "nvidia"}) is True

    def test_custom_enabled(self):
        assert config.is_api_enabled({"api_provider": "custom"}) is True

    def test_ollama_enabled(self):
        assert config.is_api_enabled({"api_provider": "ollama"}) is True

    def test_disabled(self):
        assert config.is_api_enabled({"api_provider": "disabled"}) is False

    def test_empty_dict_defaults_to_enabled(self):
        assert config.is_api_enabled({}) is True


class TestOllamaProvider:
    def test_ollama_in_providers_list(self):
        assert "ollama" in config.API_PROVIDERS

    def test_ollama_default_url(self):
        assert config.OLLAMA_DEFAULT_URL == "http://localhost:11434/v1"

    def test_resolve_ollama_no_api_key_needed(self, monkeypatch):
        # Ollama should NOT require an API key — it uses "not-needed" sentinel.
        monkeypatch.setattr(config, "get_api_key", lambda: None)
        cfg = {"api_provider": "ollama", "ollama_url": "http://localhost:11434/v1"}
        url, key = config.resolve_api_endpoint(cfg)
        assert url == "http://localhost:11434/v1"
        assert key == "not-needed"

    def test_resolve_ollama_remote_server(self, monkeypatch):
        # Any network host should work, not just localhost.
        monkeypatch.setattr(config, "get_api_key", lambda: None)
        cfg = {"api_provider": "ollama", "ollama_url": "http://192.168.1.50:11434/v1"}
        url, key = config.resolve_api_endpoint(cfg)
        assert url == "http://192.168.1.50:11434/v1"
        assert key == "not-needed"

    def test_resolve_ollama_invalid_url(self, monkeypatch):
        monkeypatch.setattr(config, "get_api_key", lambda: None)
        cfg = {"api_provider": "ollama", "ollama_url": "not-a-url"}
        try:
            config.resolve_api_endpoint(cfg)
            assert False, "should have raised"
        except ValueError as exc:
            assert "http" in str(exc).lower()


class TestOllamaModelFetch:
    def test_fetch_strips_v1_suffix(self, monkeypatch):
        """fetch_ollama_models should hit /api/tags, not /v1/api/tags."""
        captured = []
        class FakeResp:
            def read(self): return b'{"models": []}'
            def __enter__(self): return self
            def __exit__(self, *a): pass
        def fake_urlopen(req, timeout=None):
            captured.append(req.full_url if hasattr(req, 'full_url') else str(req))
            return FakeResp()
        monkeypatch.setattr(config.urllib.request, "urlopen", fake_urlopen)
        config.fetch_ollama_models("http://localhost:11434/v1")
        assert captured[0] == "http://localhost:11434/api/tags"

    def test_fetch_no_v1_suffix(self, monkeypatch):
        """Should work even if user enters URL without /v1."""
        captured = []
        class FakeResp:
            def read(self): return b'{"models": []}'
            def __enter__(self): return self
            def __exit__(self, *a): pass
        def fake_urlopen(req, timeout=None):
            captured.append(req.full_url if hasattr(req, 'full_url') else str(req))
            return FakeResp()
        monkeypatch.setattr(config.urllib.request, "urlopen", fake_urlopen)
        config.fetch_ollama_models("http://localhost:11434")
        assert captured[0] == "http://localhost:11434/api/tags"

    def test_fetch_parses_model_names(self, monkeypatch):
        class FakeResp:
            def read(self):
                return b'{"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:7b"}]}'
            def __enter__(self): return self
            def __exit__(self, *a): pass
        monkeypatch.setattr(config.urllib.request, "urlopen",
                            lambda req, timeout=None: FakeResp())
        models = config.fetch_ollama_models("http://localhost:11434/v1")
        assert models == ["llama3.1:8b", "qwen2.5:7b"]


# ══════════════════════════════════════════════════════════════════════════════
#  updater._parse_version / _version_lt
# ══════════════════════════════════════════════════════════════════════════════

class TestVersionParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("1.0.0", (1, 0, 0)),
        ("v1.2.3", (1, 2, 3)),
        ("1.2", (1, 2, 0)),
        ("1", (1, 0, 0)),
        ("", (0, 0, 0)),
        ("v", (0, 0, 0)),
        ("1.0.0-beta", (1, 0, 0)),
        ("1.2.3.4", (1, 2, 3)),
    ])
    def test_parse(self, raw, expected):
        assert updater._parse_version(raw) == expected

    @pytest.mark.parametrize("a,b,expected", [
        ("1.0.0", "1.0.1", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.1", "1.0.0", False),
        ("1.0.0", "1.1.0", True),
        ("1.1.0", "2.0.0", True),
        ("1.0.0", "0.9.9", False),
    ])
    def test_version_lt(self, a, b, expected):
        assert updater._version_lt(a, b) is expected


# ══════════════════════════════════════════════════════════════════════════════
#  updater.evaluate
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluate:
    def test_none_manifest_returns_none(self):
        assert updater.evaluate(None) is None

    def test_empty_latest_returns_none(self):
        assert updater.evaluate({"latest": ""}) is None

    def test_up_to_date_returns_none(self, monkeypatch):
        monkeypatch.setattr(updater, "__version__", "1.0.11")
        assert updater.evaluate({"latest": "1.0.11", "min_supported": "1.0.11"}) is None

    def test_optional_update(self, monkeypatch):
        monkeypatch.setattr(updater, "__version__", "1.0.10")
        result = updater.evaluate({"latest": "1.0.11", "min_supported": "1.0.0"})
        assert result is not None and result.force is False

    def test_forced_update_flag(self, monkeypatch):
        monkeypatch.setattr(updater, "__version__", "1.0.0")
        result = updater.evaluate({"latest": "1.0.11", "min_supported": "1.0.5", "force": True})
        assert result is not None and result.force is True

    def test_below_min_supported_is_forced(self, monkeypatch):
        monkeypatch.setattr(updater, "__version__", "1.0.0")
        result = updater.evaluate({"latest": "1.0.11", "min_supported": "1.0.5", "force": False})
        assert result is not None and result.force is True


# ══════════════════════════════════════════════════════════════════════════════
#  updater._download_url
# ══════════════════════════════════════════════════════════════════════════════

class TestDownloadUrl:
    def test_windows(self, monkeypatch):
        monkeypatch.setattr(updater, "platform_key", lambda: "windows")
        assert updater._download_url({"downloads": {"windows": "https://x/win.exe"}}) == "https://x/win.exe"

    def test_macos(self, monkeypatch):
        monkeypatch.setattr(updater, "platform_key", lambda: "macos")
        assert updater._download_url({"downloads": {"macos": "https://x/mac.dmg"}}) == "https://x/mac.dmg"

    def test_linux(self, monkeypatch):
        monkeypatch.setattr(updater, "platform_key", lambda: "linux_appimage")
        assert updater._download_url({"downloads": {"linux_appimage": "https://x/li.AppImage"}}) == "https://x/li.AppImage"

    def test_missing_platform_returns_none(self, monkeypatch):
        monkeypatch.setattr(updater, "platform_key", lambda: "windows")
        assert updater._download_url({"downloads": {"macos": "x"}}) is None

    def test_empty_downloads_returns_none(self, monkeypatch):
        monkeypatch.setattr(updater, "platform_key", lambda: "windows")
        assert updater._download_url({}) is None


# ══════════════════════════════════════════════════════════════════════════════
#  linux_input._parse_pynput_combo — hotkey string parser
# ══════════════════════════════════════════════════════════════════════════════

class TestParseCombo:
    @pytest.mark.parametrize("combo,valid", [
        ("<ctrl>+<alt>+e", True),
        ("<ctrl>+<alt>+<shift>+p", True),
        ("<cmd>+c", True),
        ("<super>+x", True),
        ("e", False),
        ("<ctrl>", False),
        ("<ctrl>+ab", False),
        ("<ctrl>+<win>+e", True),
        ("<control>+e", True),
        ("<ctrl>+<alt>+E", True),
    ])
    def test_validity(self, combo, valid):
        result = linux_input._parse_pynput_combo(combo)
        if valid:
            assert result is not None
            # Key is always a single lowercase alphanumeric char.
            mods, key = result
            assert len(key) == 1 and key.islower()
        else:
            assert result is None

    def test_mods_extracted(self):
        mods, key = linux_input._parse_pynput_combo("<ctrl>+<alt>+e")
        assert mods == frozenset({"ctrl", "alt"})
        assert key == "e"

    def test_whitespace_tolerated(self):
        mods, key = linux_input._parse_pynput_combo("  <ctrl> + <alt> + e  ")
        assert mods == frozenset({"ctrl", "alt"})
        assert key == "e"


# ══════════════════════════════════════════════════════════════════════════════
#  linux_input session / display discovery (systemd DISPLAY=:0 crash)
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionEnv:
    def test_stale_display_dropped_when_wayland(self, monkeypatch, tmp_path):
        runtime = tmp_path / "run"
        runtime.mkdir()
        (runtime / "wayland-0").touch()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
        monkeypatch.setattr(linux_input.os.path, "exists", lambda p: (
            str(p).endswith("wayland-0") or str(p) == str(runtime / "wayland-0")
            if "wayland" in str(p) else False
        ))
        # Use real path.exists for the wayland socket we created; force X0 missing.
        real_exists = linux_input.os.path.exists

        def _exists(path):
            s = str(path)
            if s.endswith("/X0") or s.endswith("X0"):
                return False
            return real_exists(path)

        monkeypatch.setattr(linux_input.os.path, "exists", _exists)
        linux_input.ensure_session_env()
        assert linux_input.os.environ.get("WAYLAND_DISPLAY") == "wayland-0"
        assert "DISPLAY" not in linux_input.os.environ or not linux_input.os.environ.get("DISPLAY")
        assert linux_input.is_wayland() is True
        assert linux_input.prefer_evdev_hotkeys() is True

    def test_explicit_x11_session_not_wayland(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(
            linux_input.os.path, "exists",
            lambda p: str(p).endswith("X0"),
        )
        assert linux_input.is_wayland() is False
        assert linux_input.prefer_evdev_hotkeys() is False

    def test_no_display_prefers_evdev(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(linux_input.os.path, "exists", lambda _p: False)
        assert linux_input.prefer_evdev_hotkeys() is True
