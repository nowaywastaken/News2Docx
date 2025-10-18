from __future__ import annotations

from news2docx.ai.free_models_scraper import parse_free_models


def test_parse_free_models_basic():
    html = (
        '<div class="card">'
        "  <h3>Qwen/Qwen2-7B-Instruct</h3>"
        "  <div>免费</div>"
        "  <div>输入免费 / 输出免费</div>"
        "</div>"
    )
    names = parse_free_models(html)
    assert any("Qwen2-7B-Instruct" in n for n in names)


def test_selector_fallback_env(monkeypatch):
    # Force selector primary path to fail, enable scraper fallback
    import news2docx.ai.selector as sel

    monkeypatch.setenv("N2D_USE_PRICING_SCRAPER", "1")

    class Resp:
        def raise_for_status(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(sel.requests, "get", lambda *a, **k: Resp(), raising=True)

    # Mock scrape_free_models to return a known free id
    monkeypatch.setenv("N2D_USE_PLAYWRIGHT", "0")
    monkeypatch.setattr(sel, "FREE_IDS", sel.FREE_IDS | {"Qwen/Qwen2-7B-Instruct"}, raising=True)
    monkeypatch.setattr(
        __import__("news2docx.ai.free_models_scraper", fromlist=["scrape_free_models"]),
        "scrape_free_models",
        lambda *a, **k: ["Qwen/Qwen2-7B-Instruct"],
        raising=True,
    )

    out = sel.free_chat_models()
    assert any("Qwen2-7B" in m for m in out)
