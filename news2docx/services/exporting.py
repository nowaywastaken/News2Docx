from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from news2docx.cli.common import desktop_outdir
from news2docx.export.docx import DocumentConfig, DocumentWriter, FontConfig


def _desktop_outdir() -> Path:
    # Delegate to shared helper to avoid duplication
    return desktop_outdir()


def build_document_config(conf: Dict[str, Any]) -> DocumentConfig:
    # Hard-coded defaults per requirements
    order = "zh-en"
    bilingual = True
    # Use fixed indent per requirement
    first_line_indent_inch = 0.2
    font_zh_name = str(conf.get("export_font_zh_name") or "宋体")
    font_zh_size = float(conf.get("export_font_zh_size") or 10.5)
    font_en_name = str(conf.get("export_font_en_name") or "Cambria")
    font_en_size = float(conf.get("export_font_en_size") or 10.5)
    # Fixed title size multiplier per requirement
    title_size_multiplier = 1.0
    title_bold = conf.get("export_title_bold")

    cfg = DocumentConfig(
        bilingual=bilingual,
        order=order,
        first_line_indent_inch=first_line_indent_inch,
        font_zh=FontConfig(name=font_zh_name, size_pt=font_zh_size),
        font_en=FontConfig(name=font_en_name, size_pt=font_en_size),
        title_size_multiplier=title_size_multiplier,
    )
    # Inject optional attribute respected by writer
    if title_bold is not None:
        setattr(cfg, "title_bold", bool(title_bold))
    return cfg


def compute_export_targets(
    conf: Dict[str, Any], output: Optional[Path], default_filename: str
) -> tuple[Path, Path]:
    # Hard-coded to Desktop output directory
    export_dir = _desktop_outdir()
    if output and output.suffix.lower() == ".docx":
        out_path = export_dir / output.name
    else:
        out_path = export_dir / default_filename
    return export_dir, out_path


def export_processed(
    data_or_path: Dict[str, Any] | Path,
    conf: Dict[str, Any],
    *,
    output: Optional[Path],
    split: Optional[bool],
    default_filename: str,
) -> Dict[str, Any]:
    """Export processed payload to DOCX.
    Returns a dict: {"split": bool, "paths": List[str]} or {"split": False, "path": str}
    """
    if isinstance(data_or_path, Path):
        data = json.loads(data_or_path.read_text(encoding="utf-8"))
    else:
        data = data_or_path

    cfg_doc = build_document_config(conf)

    # Last-mile sanitation on payload (avoid Note:/timestamps leaking into export)
    def _sanitize_linewise(text: str, prefixes: list, patterns: list) -> str:
        if not text:
            return text
        lines = text.splitlines()
        out = []
        import re

        for ln in lines:
            s = ln.strip()
            dropped = False
            for pref in prefixes or []:
                try:
                    if s.startswith(str(pref)):
                        dropped = True
                        break
                except Exception:
                    continue
            if dropped:
                continue
            for pat in patterns or []:
                try:
                    if re.match(pat, s):
                        dropped = True
                        break
                except Exception:
                    continue
            if not dropped:
                out.append(ln)
        return "\n".join(out).strip()

    prefixes = list(conf.get("processing_forbidden_prefixes") or [])
    patterns = list(conf.get("processing_forbidden_patterns") or [])
    try:
        data = (
            json.loads(data_or_path.read_text(encoding="utf-8"))
            if isinstance(data_or_path, Path)
            else dict(data_or_path)
        )
    except Exception:
        data = data_or_path if isinstance(data_or_path, dict) else {}
    if isinstance(data, dict):
        arts = data.get("articles") or []
        for a in arts:
            if isinstance(a, dict):
                a["adjusted_content"] = _sanitize_linewise(
                    a.get("adjusted_content") or "", prefixes, patterns
                )
                a["translated_content"] = _sanitize_linewise(
                    a.get("translated_content") or "", prefixes, patterns
                )
        # 免费通道：只导出成功项，丢弃失败/未翻译项
        try:
            import os as _os

            if (_os.getenv("N2D_PIPELINE_MODE", "").strip().lower() == "free"):
                data["articles"] = [
                    a
                    for a in arts
                    if isinstance(a, dict)
                    and bool(a.get("success", True))
                    and (str(a.get("translated_content") or "").strip() != "")
                ]
        except Exception:
            pass
    # Use sanitized 'data' for export
    data_or_path = data
    export_dir, out_path = compute_export_targets(conf, output, default_filename)
    # Hard-coded: always split per article
    split_flag = True if split is None else bool(split)

    writer = DocumentWriter(cfg_doc)
    if split_flag:
        paths = writer.write_per_article(data, str(export_dir))
        return {"split": True, "paths": paths}
    else:
        writer.write_from_processed(data, str(out_path))
        return {"split": False, "path": str(out_path)}
