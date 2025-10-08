from __future__ import annotations

from pathlib import Path

from index import load_app_config


def test_autogen_config_from_example(tmp_path: Path, monkeypatch) -> None:
    # Arrange: only example exists; disable encryption for deterministic behavior
    example = tmp_path / "config.example.yml"
    example.write_text(
        """
security:
  enable_encryption: false
app:
  name: "News2Docx UI"
openai_api_base: "https://api.siliconflow.cn/v1"
openai_api_key: "dummy"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    cfg_path = tmp_path / "config.yml"

    # Act: load should auto-create config.yml from example
    cfg = load_app_config(str(cfg_path))

    # Assert
    assert cfg_path.exists(), "config.yml should be created when missing"
    text = cfg_path.read_text(encoding="utf-8")
    assert "enable_encryption: false" in text
    assert isinstance(cfg, dict)
    assert cfg.get("app", {}).get("name") == "News2Docx UI"

