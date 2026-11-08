# -*- coding: utf-8 -*-
"""Compose the 5 top-level docs from docs/chapters/*.md.

Chapter content is preserved verbatim; each chapter becomes one H1 section
inside its parent document.  Run from repo root:  python scripts/compose_docs.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "chapters"
OUT = ROOT / "docs"


def load(name: str) -> str:
    text = (SRC / name).read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]           # drop the chapter's own H1; we re-number
    return "\n".join(lines).strip()


def compose(filename: str, title: str, intro: str, parts: list) -> None:
    body = [f"# {title}", "", intro, ""]
    for part in parts:
        name = part[0] if isinstance(part, tuple) else part
        text = load(name)
        body.extend([text, "", "---", ""])
    (OUT / filename).write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {filename}")


compose(
    "01_产品需求与验收.md",
    "灵枢 NeuroAxis · 产品需求、品牌与验收",
    "> 源文档：《15 灵枢 NeuroAxis 设计文档》第 0/1/11 章与附录。本文回答「做什么、给谁做、做到什么程度算成」。",
    [
        ("00_problem.md", "这份文档解决什么问题"),
        ("01_product.md", "产品定义与核心闭环"),
        ("11_milestones.md", "里程碑与验收总表"),
        ("20_delivery-boundary.md", "对外交付边界"),
        ("99_appendix.md", "附录（D1 样例 / 术语 / 参考）"),
    ],
)

compose(
    "02_技术设计.md",
    "灵枢 NeuroAxis · 产品技术设计",
    "> 源文档第 2~10、13~19 章。架构、工程模型、Agent、仿真台、导出、数据、接口、安全与互操作规范。",
    [
        ("02_architecture.md", "总体架构"),
        ("03_spec-ir-st.md", "工程模型：Spec → IR → ST（三段式）"),
        ("04_agent.md", "AI Agent 设计"),
        ("05_simulation.md", "仿真台（产品的护城河）"),
        ("06_debug-loop.md", "诊断与修复闭环"),
        ("07_export-adapters.md", "导出与厂商适配（A/B/C 三档）"),
        ("08_data.md", "数据架构"),
        ("09_interfaces.md", "接口"),
        ("13_static-rules.md", "静态检查规则全集（40 条）"),
        ("14_verification.md", "验证体系（五道闸门 / CI / 评测集）"),
        ("15_interop.md", "互操作规范"),
        ("16_ops.md", "运维生产化"),
        ("17_security-ops.md", "安全生产化（威胁模型与密钥）"),
        ("18_hmi-cli-acceptance.md", "HMI 生成、CLI 与 P1/P2 验收细目"),
        ("19_rag-agent-framework.md", "RAG 知识库与 Agent 框架"),
        ("21_spec-schema.md", "Spec JSON Schema 与 D1 样例工程全量文件"),
    ],
)

compose(
    "03_实施计划.md",
    "灵枢 NeuroAxis · 分阶段实施计划",
    "> 依据《02_技术设计》与《01_产品需求与验收》的里程碑拆解为可排期的周级任务。",
    [("99_implementation-plan.md", "实施计划")],
)

compose(
    "04_阶段验收标准.md",
    "灵枢 NeuroAxis · 各阶段验收标准",
    "> 每个阶段结束时按此逐条打勾；不达标即停下修复，不往前走。",
    [("99_acceptance-criteria.md", "阶段验收标准")],
)

compose(
    "05_测试与部署.md",
    "灵枢 NeuroAxis · 测试与部署",
    "> 测试分层、CI 门禁、发布与部署、备份升级、错误处置。",
    [("99_test-deploy.md", "测试与部署")],
)
