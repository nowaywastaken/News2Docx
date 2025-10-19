from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from news2docx.cli.common import desktop_outdir
from news2docx.export.docx import DocumentConfig, DocumentWriter, FontConfig


def build_document_config(conf: Dict[str, Any]) -> DocumentConfig:
    """构建文档配置。"""
    cfg = DocumentConfig(
        bilingual=True,
        order="zh-en",
        first_line_indent_inch=0.2,
        font_zh=FontConfig(
            name=str(conf.get("export_font_zh_name") or "宋体"),
            size_pt=float(conf.get("export_font_zh_size") or 10.5),
        ),
        font_en=FontConfig(
            name=str(conf.get("export_font_en_name") or "Cambria"),
            size_pt=float(conf.get("export_font_en_size") or 10.5),
        ),
        title_size_multiplier=1.0,
    )
    if (title_bold := conf.get("export_title_bold")) is not None:
        setattr(cfg, "title_bold", bool(title_bold))
    return cfg


def export_processed(
    data_or_path: Dict[str, Any] | Path,
    conf: Dict[str, Any],
    *,
    output: Optional[Path],
    split: Optional[bool],
    default_filename: str,
) -> Dict[str, Any]:
    """导出处理后的文章为 DOCX 文件。"""
    import os
    import re
    
    # 加载数据
    data = (
        json.loads(data_or_path.read_text(encoding="utf-8"))
        if isinstance(data_or_path, Path)
        else dict(data_or_path) if isinstance(data_or_path, dict) else {}
    )
    
    # 清理内容
    prefixes = list(conf.get("processing_forbidden_prefixes") or [])
    patterns = list(conf.get("processing_forbidden_patterns") or [])
    
    def _sanitize(text: str) -> str:
        if not text:
            return text
        lines = []
        for ln in text.splitlines():
            s = ln.strip()
            if any(s.startswith(str(p)) for p in prefixes):
                continue
            if any(re.match(pat, s) for pat in patterns):
                continue
            lines.append(ln)
        return "\n".join(lines).strip()
    
    # 处理文章列表
    if isinstance(data, dict):
        arts = data.get("articles") or []
        for a in arts:
            if isinstance(a, dict):
                a["adjusted_content"] = _sanitize(a.get("adjusted_content") or "")
                a["translated_content"] = _sanitize(a.get("translated_content") or "")
        
        # 免费模式：只导出成功翻译的文章
        if os.getenv("N2D_PIPELINE_MODE", "").strip().lower() == "free":
            data["articles"] = [
                a for a in arts
                if isinstance(a, dict)
                and a.get("success", True)
                and a.get("translated_content", "").strip()
            ]
    
    # 确定输出路径
    export_dir = desktop_outdir()
    out_path = (
        export_dir / output.name
        if output and output.suffix.lower() == ".docx"
        else export_dir / default_filename
    )
    
    # 导出
    cfg_doc = build_document_config(conf)
    writer = DocumentWriter(cfg_doc)
    split_flag = True if split is None else bool(split)
    
    if split_flag:
        paths = writer.write_per_article(data, str(export_dir))
        return {"split": True, "paths": paths}
    else:
        writer.write_from_processed(data, str(out_path))
        return {"split": False, "path": str(out_path)}
