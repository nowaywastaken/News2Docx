from __future__ import annotations

from pathlib import Path

from news2docx.infra.secure_config import secure_load_config


def test_secure_load_does_not_modify_example(tmp_path):
    example = Path("config.example.yml")
    original = example.read_text(encoding="utf-8")
    cfg = secure_load_config(str(example))
    assert isinstance(cfg, dict)
    # Should not mutate example file
    after = example.read_text(encoding="utf-8")
    assert after == original

