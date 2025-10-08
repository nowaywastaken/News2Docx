"""Lightweight smoke checks that don't hit network.

Run: python scripts/smoke.py
"""

from __future__ import annotations

from pathlib import Path


def check_docx_writer() -> None:
    from news2docx.export.docx import DocumentConfig, DocumentWriter

    processed = {
        "articles": [
            {
                "original_title": "Sample Title",
                "translated_title": "Sample Title (Chinese)",
                "original_content": "Paragraph A.\n\nParagraph B.",
                "adjusted_content": "Paragraph A.\n\nParagraph B.",
                "translated_content": "Paragraph Alpha.\n\nParagraph Beta.",
            }
        ]
    }

    out = Path("_smoke.docx")
    writer = DocumentWriter(DocumentConfig())
    writer.write_from_processed(processed, str(out))
    assert out.exists() and out.stat().st_size > 0
    out.unlink(missing_ok=True)


def main() -> None:
    check_docx_writer()
    print("smoke ok")


if __name__ == "__main__":
    main()
