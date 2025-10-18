from __future__ import annotations

from news2docx.process import engine as eng


def _mk_text(n: int) -> str:
    return "\n\n".join([f"Para {i + 1} content." for i in range(n)])


def test_parallel_translation_chunking(monkeypatch):
    monkeypatch.setenv("N2D_TRANSLATION_MODE", "parallel")

    # Provide two models to map across chunks
    monkeypatch.setattr(eng, "free_chat_models", lambda timeout=30: ["m1", "m2"], raising=True)

    # Make call_ai_api echo model and text to observe ordering and coverage
    def fake_call(system_prompt: str, user_prompt: str, model=None, *_args, **_kwargs) -> str:
        # Identify the chunk by extracting the last segment after two newlines separation.
        # Our build_translation_prompts places text at the end of user_prompt.
        parts = user_prompt.split("\n\n")
        text = parts[-1] if parts else user_prompt
        m = model or "auto"
        return f"[{m}] {text}"

    monkeypatch.setattr(eng, "call_ai_api", fake_call, raising=True)

    text = _mk_text(4)  # 4 paragraphs -> with 2 models, expect 2 chunks
    out = eng._translate_parallel_by_models(text, target_lang="Chinese")

    # Must contain contributions from both models in order
    assert out.index("[m1]") < out.index("[m2]")
    assert "Para 1" in out and "Para 4" in out
