"""Evidence package generation (14.1 append-only verdicts -> report).

Markdown is the canonical format (human reviewable, diffable); PDF via
WeasyPrint is optional - when the package is missing the report stays
markdown (16.2: export must not silently fail, we say so in the output).
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from plcagent.gates import PipelineResult


def render_markdown(pipeline: PipelineResult, project: str) -> str:
    """One evidence report: gates, details, verdict hash, spec hash."""
    lines = [
        f"# NeuroAxis 证据包 — {project}",
        "",
        f"- SpecHash: `{pipeline.spec_hash}`",
        f"- VerdictHash: `{pipeline.verdict_hash}`",
        f"- 总判定: **{'PASS' if pipeline.all_passed else 'FAIL'}**",
        "",
        "| 闸门 | 判定 | 详情 |",
        "|---|---|---|",
    ]
    for result in pipeline.results:
        mark = "✅ PASS" if result.passed else "❌ FAIL"
        detail = "; ".join(result.details) or "-"
        lines.append(f"| {result.gate} | {mark} | {detail} |")
    lines.append("")
    lines.append("生成时间戳不写入报告：报告内容仅由 Spec 与套件决定，")
    lines.append("同输入重跑字节一致（确定性要求，15.2）。")
    return "\n".join(lines) + "\n"


def write_report(pipeline: PipelineResult, project: str,
                 out_dir: str | Path) -> dict[str, str]:
    """Write md (+pdf when WeasyPrint available); returns written paths."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    md_path = out_path / f"report_{project}.md"
    md_path.write_text(render_markdown(pipeline, project),
                       encoding="utf-8", newline="\n")
    written["md"] = str(md_path)

    try:
        from weasyprint import HTML  # optional dependency

        pdf_path = out_path / f"report_{project}.pdf"
        HTML(string=render_markdown(pipeline, project)).write_pdf(pdf_path)
        written["pdf"] = str(pdf_path)
    except ImportError:
        pass                  # md is the canonical artefact; pdf is optional
    return written


def verdict_json(pipeline: PipelineResult) -> str:
    """Machine-readable verdict for CI (JUnit-like consumer)."""
    payload = {
        "all_passed": pipeline.all_passed,
        "spec_hash": pipeline.spec_hash,
        "verdict_hash": pipeline.verdict_hash,
        "gates": [asdict(r) if is_dataclass(r) else r.__dict__
                  for r in pipeline.results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
