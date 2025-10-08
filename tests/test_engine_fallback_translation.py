# -*- coding: utf-8 -*-
from __future__ import annotations

from news2docx.process import engine as eng


def test_process_article_fallback_regenerates_translation(monkeypatch):
    # Force a very high min_words to trigger the fallback branch
    monkeypatch.setattr(
        eng,
        "_load_cleaning_config",
        lambda: {"prefixes": [], "patterns": [], "min_words": 10000},
        raising=True,
    )

    def fake_call(system_prompt: str, user_prompt: str, **_kwargs) -> str:
        # Extract the text payload after the last empty line
        parts = user_prompt.split("\n\n")
        text = parts[-1] if parts else user_prompt
        if "title translator" in system_prompt:
            return "ZH-TITLE:" + text
        if "translator" in system_prompt:
            return "ZH:" + text
        if "news editor" in system_prompt:
            # Editing step returns original English back (short),
            # so word count remains far below the forced threshold.
            return text
        return text

    monkeypatch.setattr(eng, "call_ai_api", fake_call, raising=True)

    a = eng.Article(index=1, url="http://x/1", title="Hello", content="Short text only.")

    res = eng.process_article(a, target_lang="Chinese")

    # Fallback should set adjusted_content to the adjusted_raw (original editor output)
    assert res["adjusted_content"].startswith("Short text"), "adjusted_content should be reverted"

    # And translation should be regenerated to match the reverted English content
    assert res["translated_content"].startswith(
        "ZH:" + res["adjusted_content"]
    ), "translation must match reverted English content"

    # Word count reflects final adjusted content
    from news2docx.process.engine import _count_words

    assert res["adjusted_word_count"] == _count_words(
        res["adjusted_content"]
    ), "adjusted_word_count must reflect final content"

