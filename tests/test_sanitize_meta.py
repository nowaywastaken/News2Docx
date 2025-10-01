# -*- coding: utf-8 -*-
from __future__ import annotations

from news2docx.process.engine import _sanitize_meta


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

