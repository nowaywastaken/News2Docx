from __future__ import annotations

# Ensure project root is importable for tests
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Consolidated imports for tests (ruff E402 compliance)
from index import load_app_config, prepare_logging
from news2docx.core.utils import now_stamp, safe_filename
from news2docx.infra.logging import unified_print
from news2docx.infra.secure_config import secure_load_config
from news2docx.process import engine as eng
from news2docx.process.engine import _sanitize_meta
from news2docx.services.processing import articles_from_json
from news2docx.services.runs import clean_runs, runs_base_dir


def test_autogen_config_from_example(tmp_path: Path, monkeypatch) -> None:
    example = tmp_path / "config.example.yml"
    example.write_text(
        (
            "security:\n"
            "  enable_encryption: false\n"
            "app:\n"
            "  name: \"News2Docx UI\"\n"
            "openai_api_base: \"https://api.siliconflow.cn/v1\"\n"
            "openai_api_key: \"dummy\"\n"
        ),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "config.yml"
    cfg = load_app_config(str(cfg_path))
    assert cfg_path.exists()
    text = cfg_path.read_text(encoding="utf-8")
    assert "enable_encryption: false" in text
    assert isinstance(cfg, dict)
    assert cfg.get("app", {}).get("name") == "News2Docx UI"


# ---- tests from test_machine_encryption.py ----


def _write_yaml(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8")


def test_machine_bound_encrypt_and_decrypt(tmp_path):
    cfg_path = tmp_path / "config.yml"
    _write_yaml(
        cfg_path,
        (
            "security:\n"
            "  enable_encryption: true\n"
            "openai_api_key: PLAINTEXT_KEY\n"
            "crawler_api_token: TKN\n"
        ),
    )
    cfg = secure_load_config(str(cfg_path))
    assert cfg["openai_api_key"] == "PLAINTEXT_KEY"
    saved = cfg_path.read_text(encoding="utf-8")
    assert "encmach:" in saved
    before = cfg_path.read_text(encoding="utf-8")
    cfg2 = secure_load_config(str(cfg_path))
    after = cfg_path.read_text(encoding="utf-8")
    assert cfg2["openai_api_key"] == "PLAINTEXT_KEY"
    assert before == after


# ---- tests from test_secure_config.py ----


def test_secure_load_does_not_modify_example(tmp_path):
    example = Path("config.example.yml")
    original = example.read_text(encoding="utf-8")
    cfg = secure_load_config(str(example))
    assert isinstance(cfg, dict)
    after = example.read_text(encoding="utf-8")
    assert after == original


# ---- tests from test_sanitize_meta.py ----


def test_sanitize_meta_basic_prefix():
    text = "Note: something should not appear\nReal content line 1\nCBS News"
    cleaned, removed, kinds = _sanitize_meta(text, ["Note:", "CBS News"], [])
    assert "Real content" in cleaned
    assert "Note:" not in cleaned
    assert removed >= 2
    assert any(k.startswith("prefix:") for k in kinds)


def test_sanitize_meta_datetime_pattern():
    pat = r"(?i)^\s*(September|October)\s+\d{1,2},\s+\d{4}\s*/\s*\d{1,2}:\d{2}\s*(AM|PM)\s*[A-Z]{2,4}\s*/\s*([A-Za-z\s]+)$"
    text = "September 30, 2025 / 9:09 PM EDT / CBS News\nStory body line"
    cleaned, removed, kinds = _sanitize_meta(text, [], [pat])
    assert "Story body" in cleaned
    assert "September 30" not in cleaned
    assert removed == 1
    assert any(k.startswith("pattern:") for k in kinds)


# ---- tests from test_services_processing.py ----


def test_articles_from_json_basic():
    data = {
        "articles": [
            {
                "id": 1,
                "url": "http://example.com/a",
                "title": "T",
                "content": "Hello world",
                "content_length": 11,
                "word_count": 2,
            }
        ]
    }
    arts = articles_from_json(data)
    assert len(arts) == 1
    a = arts[0]
    assert a.index == 1
    assert a.url.endswith("/a")
    assert a.title == "T"
    assert a.content.startswith("Hello")


# ---- tests from test_services_runs.py ----


def test_runs_base_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "myruns"))
    base = runs_base_dir()
    assert str(base).endswith("myruns")


def test_clean_runs(tmp_path):
    base = tmp_path / "runs"
    (base / "r1").mkdir(parents=True)
    (base / "r2").mkdir(parents=True)
    (base / "r1").touch()
    (base / "r2").touch()
    deleted = clean_runs(base, keep=1)
    assert len(deleted) == 1
    assert (base / "r1").exists() ^ (base / "r2").exists()


# ---- tests from test_ui_basic.py ----


def test_config_example_ui_structure():
    p = Path("config.example.yml")
    cfg = load_app_config(str(p))
    assert isinstance(cfg, dict)
    assert "ui" in cfg and isinstance(cfg["ui"], dict)
    ui = cfg["ui"]
    assert int(ui["fixed_width"]) == 350
    assert int(ui["fixed_height"]) == 600
    assert bool(ui["high_dpi"]) is True


def test_prepare_logging_console_only(tmp_path):
    log_path = tmp_path / "tmp_log.txt"
    prepare_logging(str(log_path))
    unified_print("hello", "test", "case", level="info")
    assert not log_path.exists()


# ---- tests from test_utils.py ----


def test_safe_filename_basic():
    assert safe_filename("a:b*c?.txt").endswith(".txt")
    assert "?" not in safe_filename("q?.md")


def test_now_stamp_format():
    ts = now_stamp()
    assert len(ts) == 15 and ts[8] == "_"


# ---- tests from test_engine_fallback_translation.py ----


def test_process_article_fallback_regenerates_translation(monkeypatch):
    monkeypatch.setattr(
        eng,
        "_load_cleaning_config",
        lambda: {"prefixes": [], "patterns": [], "min_words": 10000},
        raising=True,
    )

    def fake_call(system_prompt: str, user_prompt: str, **_kwargs) -> str:
        parts = user_prompt.split("\n\n")
        text = parts[-1] if parts else user_prompt
        if "title translator" in system_prompt:
            return "ZH-TITLE:" + text
        if "translator" in system_prompt:
            return "ZH:" + text
        if "news editor" in system_prompt:
            return text
        return text

    monkeypatch.setattr(eng, "call_ai_api", fake_call, raising=True)
    a = eng.Article(index=1, url="http://x/1", title="Hello", content="Short text only.")
    res = eng.process_article(a, target_lang="Chinese")
    assert res["adjusted_content"].startswith("Short text")
    from news2docx.process.engine import _count_words

    assert res["adjusted_word_count"] == _count_words(res["adjusted_content"])  # type: ignore[name-defined]
