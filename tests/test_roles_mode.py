from __future__ import annotations

from typing import Any

from news2docx.process import engine as eng


def test_roles_mode_fallback_between_models(monkeypatch):
    monkeypatch.setenv("N2D_AI_ROLES", "1")
    monkeypatch.setenv("N2D_EDITOR_MODELS", "bad_editor,good_editor")
    monkeypatch.setenv("N2D_TRANSLATOR_MODELS", "bad_trans,good_trans")

    # Fake call_ai_api: return too-short text for bad_editor; valid long text for good_editor
    def fake_call(system_prompt: str, user_prompt: str, model=None, *_a: Any, **_k: Any) -> str:
        parts = user_prompt.split("\n\n")
        text = parts[-1] if parts else user_prompt
        if model == "bad_editor":
            return "short"  # word count fails
        if model == "good_editor":
            return ("word " * 420).strip()  # ~420 words
        if model == "bad_trans":
            return ""  # invalid
        if model == "good_trans":
            return "ZH:" + text.replace("%", " ")
        # default
        return text

    monkeypatch.setattr(eng, "call_ai_api", fake_call, raising=True)

    a = eng.Article(index=1, url="https://x/1", title="T", content=("Para A." + " ") * 500)
    res = eng.process_article(a, target_lang="Chinese")

    assert res["success"] is True
    # adjusted_content should be long enough (>400 words)
    assert eng._count_words(res["adjusted_content"]) >= 400
    # translated_content should not be empty
    assert res["translated_content"].strip() != ""
