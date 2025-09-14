from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from news2docx.export.docx import DocumentWriter, DocumentConfig, FontConfig


def _desktop_outdir() -> Path:
    home = Path.home()
    desktop = home / "Desktop"
    folder_name = "\u82f1\u6587\u65b0\u95fb\u7a3f"
    outdir = desktop / folder_name
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def build_document_config(conf: Dict[str, Any]) -> DocumentConfig:
    order = str(conf.get("export_order") or "zh-en").lower()
    bilingual = not bool(conf.get("export_mono") or False)
    first_line_indent_cm = float(conf.get("export_first_line_indent_cm") or 0.74)
    font_zh_name = str(conf.get("export_font_zh_name") or "SimSun")
    font_zh_size = float(conf.get("export_font_zh_size") or 10.5)
    font_en_name = str(conf.get("export_font_en_name") or "Cambria")
    font_en_size = float(conf.get("export_font_en_size") or 10.5)
    title_size_multiplier = float(conf.get("export_title_size_multiplier") or 1.0)
    title_bold = conf.get("export_title_bold")

    cfg = DocumentConfig(
        bilingual=bilingual,
        order=order,
        first_line_indent_cm=first_line_indent_cm,
        font_zh=FontConfig(name=font_zh_name, size_pt=font_zh_size),
        font_en=FontConfig(name=font_en_name, size_pt=font_en_size),
        title_size_multiplier=title_size_multiplier,
    )
    # Inject optional attribute respected by writer
    if title_bold is not None:
        setattr(cfg, "title_bold", bool(title_bold))
    return cfg


def compute_export_targets(conf: Dict[str, Any], output: Optional[Path], default_filename: str) -> tuple[Path, Path]:
    out_dir_cfg = conf.get("export_out_dir")
    export_dir = Path(str(out_dir_cfg)) if out_dir_cfg else _desktop_outdir()
    if output and output.suffix.lower() == ".docx":
        out_path = export_dir / output.name
    else:
        out_path = export_dir / default_filename
    return export_dir, out_path


def export_processed(data_or_path: Dict[str, Any] | Path, conf: Dict[str, Any], *, output: Optional[Path], split: Optional[bool], default_filename: str) -> Dict[str, Any]:
    """Export processed payload to DOCX.
    Returns a dict: {"split": bool, "paths": List[str]} or {"split": False, "path": str}
    """
    if isinstance(data_or_path, Path):
        data = json.loads(data_or_path.read_text(encoding="utf-8"))
    else:
        data = data_or_path

    cfg_doc = build_document_config(conf)
    export_dir, out_path = compute_export_targets(conf, output, default_filename)
    split_flag = split if split is not None else bool(conf.get("export_split") if conf.get("export_split") is not None else True)

    writer = DocumentWriter(cfg_doc)
    if split_flag:
        paths = writer.write_per_article(data, str(export_dir))
        return {"split": True, "paths": paths}
    else:
        writer.write_from_processed(data, str(out_path))
        return {"split": False, "path": str(out_path)}

