from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Any, List

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from news2docx.infra.logging import unified_print


@dataclass
class FontConfig:
    name: str
    size_pt: float


@dataclass
class DocumentConfig:
    first_line_indent_cm: float = 0.74  # ~0.29 inch
    font_zh: FontConfig = FontConfig(name="Microsoft YaHei", size_pt=11)
    font_en: FontConfig = FontConfig(name="Times New Roman", size_pt=11)
    title_size_multiplier: float = 1.0
    bilingual: bool = True  # 输出中英双语
    order: str = "zh-en"  # zh-en 或 en-zh


def _safe_title(s: str) -> str:
    s = (s or "").strip()
    return s if s else "Untitled"


def _split_paragraphs(text: str) -> List[str]:
    if not text:
        return []
    t = text.strip()
    if "%%" in t:
        parts = [p.strip() for p in t.split("%%") if p.strip()]
        return parts
    # fallback by blank lines
    parts = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    if parts:
        return parts
    # final fallback: split sentences for very short text
    sents = [p.strip() for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    return sents


class DocumentWriter:
    def __init__(self, cfg: DocumentConfig | None = None) -> None:
        self.cfg = cfg or DocumentConfig()

    def _apply_font(self, run, zh: bool) -> None:
        if zh:
            run.font.name = self.cfg.font_zh.name
            run.font.size = Pt(self.cfg.font_zh.size_pt)
        else:
            run.font.name = self.cfg.font_en.name
            run.font.size = Pt(self.cfg.font_en.size_pt)

    def _write_title(self, doc: Document, zh_title: str, en_title: str) -> None:
        # Chinese title
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(_safe_title(zh_title))
        self._apply_font(r, zh=True)
        r.font.bold = True
        # English title
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r2 = p2.add_run(_safe_title(en_title))
        self._apply_font(r2, zh=False)
        r2.font.bold = True

    def _write_block(self, doc: Document, paras: List[str], zh: bool) -> None:
        for para in paras:
            p = doc.add_paragraph()
            r = p.add_run(para)
            self._apply_font(r, zh=zh)

    def write_from_processed(self, processed: Dict[str, Any], output_path: str) -> str:
        """基于 ai_processor 两步法输出结构生成 DOCX。

        预期 processed 结构包含 `articles: [ {original_title, translated_title, adjusted_content, translated_content, ...} ]`
        """
        articles = processed.get("articles", []) if isinstance(processed, dict) else []
        if not articles:
            raise ValueError("处理结果为空，无法导出 DOCX。")

        doc = Document()

        for idx, art in enumerate(articles, start=1):
            zh_title = art.get("translated_title") or art.get("original_title") or ""
            en_title = art.get("original_title") or ""
            en_content = art.get("adjusted_content") or art.get("original_content") or ""
            zh_content = art.get("translated_content") or ""

            self._write_title(doc, zh_title, en_title)

            en_paras = _split_paragraphs(en_content)
            zh_paras = _split_paragraphs(zh_content)

            if self.cfg.bilingual:
                if self.cfg.order == "en-zh":
                    self._write_block(doc, en_paras, zh=False)
                    self._write_block(doc, zh_paras, zh=True)
                else:
                    self._write_block(doc, zh_paras, zh=True)
                    self._write_block(doc, en_paras, zh=False)
            else:
                # 默认仅中文
                self._write_block(doc, zh_paras, zh=True)

            if idx < len(articles):
                doc.add_page_break()

        unified_print(f"已生成 DOCX：{output_path}", "export", "docx")
        doc.save(output_path)
        return output_path

