# -*- coding: utf-8 -*-
"""Compose the 5 top-level docs from docs/chapters/*.md.

Chapter headings keep their original numbering so all cross references
(15.1 / V1~V16 / 19.4 ...) stay valid.  Run from repo root:
python scripts/compose_docs.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "chapters"
OUT = ROOT / "docs"


def load(name: str) -> str:
    lines = (SRC / name).read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]           # drop the chapter's own H1
    return "\n".join(lines).strip()


def compose(filename: str, title: str, intro: str, parts: list) -> None:
    body = [f"# {title}", "", intro, ""]
    for name in parts:
        body.extend([load(name), "", "---", ""])
    (OUT / filename).write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {filename}")


compose(
    "01_产品需求与验收.md",
    "灵枢 NeuroAxis · 产品需求、品牌与验收",
    "> 覆盖原设计文档第 0/1/11/20 章与附录。本文回答「做什么、给谁做、做到什么程度算成」。",
    ["00_problem.md", "01_product.md", "11_milestones.md", "20_delivery-boundary.md", "99_appendix.md"],
)

compose(
    "02_技术设计.md",
    "灵枢 NeuroAxis · 产品技术设计",
    "> 覆盖原设计文档第 2~10、13~19、21 章。架构、工程模型、Agent、仿真台、导出、数据、接口、静态检查 40 条、验证体系、互操作、运维与安全。",
    [
        "02_architecture.md", "03_spec-ir-st.md", "04_agent.md", "05_simulation.md",
        "06_debug-loop.md", "07_export-adapters.md", "08_data.md", "09_interfaces.md",
        "13_static-rules.md", "14_verification.md", "15_interop.md", "16_ops.md",
        "17_security-ops.md", "18_hmi-cli-acceptance.md", "19_rag-agent-framework.md",
        "21_spec-schema.md",
    ],
)

compose(
    "03_实施计划.md",
    "灵枢 NeuroAxis · 分阶段实施计划",
    "> 依据《02_技术设计》与《01_产品需求与验收》的里程碑拆解为可排期的周级任务。",
    ["99_implementation-plan.md"],
)

compose(
    "04_阶段验收标准.md",
    "灵枢 NeuroAxis · 各阶段验收标准",
    "> 每个阶段结束时按此逐条打勾；不达标即停下修复，不往前走。",
    ["99_acceptance-criteria.md"],
)

compose(
    "05_测试与部署.md",
    "灵枢 NeuroAxis · 测试与部署",
    "> 测试分层、CI 门禁、发布与部署、备份升级、错误处置。",
    ["99_test-deploy.md"],
)
