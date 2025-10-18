from __future__ import annotations

import os

from news2docx.process import engine as eng


def test_adjust_word_count_uses_env_bounds(monkeypatch, tmp_path):
    # Ensure no local config.yml interferes
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("N2D_WORD_MIN", "2")

    # Text has 3 words -> should pass without change and count==3 (仅校验下限)
    text = "alpha beta gamma"
    out, wc = eng._adjust_word_count(text)
    assert wc == 3
    assert out.strip().startswith("alpha")
