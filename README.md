# 灵枢 NeuroAxis

**工业智能开发平台：PLC 开发 · 模拟调试 · 验证门禁 · 知识库 · 错误排查**

> 一个"从工艺描述到可运行 PLC 程序"的 AI 工程 Agent——它读需求、写程序、在虚拟设备上把程序跑通、自己找出错在哪并修好，最后交出人和测试证据，人才把程序下到真机。

| 项 | 内容 |
|---|---|
| 技术栈 | Python 3.12（LangGraph 编排 + LlamaIndex 知识库 + FastAPI/SSE）+ Vue 3 工作台 + PostgreSQL 16（关系+pgvector）+ RustFS 对象存储（S3 兼容）+ Redis（缓存&队列）+ 自研 ST 子集解释器 + matIEC 兼容导出 + 云 LLM API（多供应商切换） |
| 定位 | 下位机 AI 编程（作为姊妹项目 [SmartDock](https://github.com/smart-open/SmartDock) 上位平台的 `kind: Copilot` 能力插件挂接） |
| 架构全景图 | docs/architecture-overview.svg（六层技术架构一图总览） |
| 文档体系 | 5 份顶层文档 + `docs/chapters/` 分章源文件，见下「文档导航」 |

## 三条铁律

1. **LLM 永远不直接产出交付物**——LLM 产出结构化 IR，确定性生成器产出 ST。
2. **仿真台是测试台，不是演示**——五道闸门全自动、不可跳过。
3. **真机写入永远人工闸门**——仿真环境内为所欲为，真机一字节都写不进去。

## 核心闭环

```
工艺描述 → Agent 澄清+生成 Spec → 人工评审 → IR→ST → 静态检查(40+规则)
→ 仿真台(确定性软PLC+虚拟设备) → 诊断修复(≤5轮) → 证据包 → 人工批准 → 导出交付
```

## 当前实现状态（P0 W1：确定性内核）

ST 子集解释器 + 虚拟时钟 + 扫描循环 + 轨迹摘要已可运行，验收 A2（同输入 N 次运行轨迹 SHA256 逐字节一致）通过：

```bash
pip install -e ".[dev]"
python -m plcagent verify --runs 100    # PASS: trace SHA256 = f3b3ffda...
python -m plcagent infra                # PG / Redis / RustFS 连通性
python -m pytest                        # 单元 + API 测试
```

## 代码结构（前后端分离）

```
src/plcagent/            后端包（src 布局，测试跑安装后的包）
├── st/                  ST 语言内核（纯函数，零 IO，禁止 import trace/）
│   ├── types.py         类型系统：整数回绕、REAL=float32、TIME=1ms、BOOL 严格
│   ├── lexer.py         词法分析（注释、T# 时间字面量）
│   ├── ast_nodes.py     冻结 dataclass AST
│   ├── parser.py        递归下降解析（运算优先级、CASE/FOR/WHILE）
│   └── interp.py        扫描循环执行器：TON 定时器、S09 循环保护、
│                        C99 截断除法、仪器化钩子（覆盖/轨迹）
├── trace/               确定性基础设施
│   ├── clock.py         VirtualClock（步长白名单 1/5/10/20/50ms）
│   └── recorder.py      TraceRecorder（轨迹事件 → 规范化 JSON → SHA256）
├── examples/            典型场景（分拣机 sorter：启动脉冲/光电/急停）
├── verify.py            验收 A2：N 次运行摘要一致性检查
├── config.py            基础设施配置（env > config/infra.toml > 默认，向上搜索）
├── storage/             PostgreSQL / Redis / RustFS 客户端（懒加载驱动）
├── infra.py             三服务连通性聚合检查
├── api/                 FastAPI 服务层（依赖 core，core 不感知 HTTP）
│   ├── schemas.py       Pydantic 请求/响应模型
│   ├── deps.py          统一错误封装 + 可选 X-API-Key 鉴权
│   ├── routes.py        /health /infra /verify（薄路由）
│   └── app.py           ASGI 工厂 + CORS 白名单
└── cli.py               plcagent verify / infra 命令

web/                     前端（Vue 3 + Vite，仅通过 /api/v1 HTTP 调用后端）
├── src/api/             axios 客户端（API key 注入、错误统一解包）
├── src/views/           工作台页面（服务状态/基础设施/验证面板）
└── vite.config.js       dev 代理 /api → :8000

tests/                   pytest（单元 + API；integration 标记需真实基础设施）
scripts/                 工具脚本（switch_env.py 环境切换、check_infra.py）
config/                  infra.toml（密钥，gitignored）/ infra.example.toml（模板）
docs/                    设计文档（见下）
```

### 分层铁则

- 依赖方向单向：`api → verify/examples → st/trace`，`st/` 不 import 任何上层。
- `st/` 内禁止 `time`/`random`——时间只来自 VirtualClock，保证可复现。
- AST 全部 frozen dataclass；解释器数值语义与 matIEC 对齐（见 docs 15.1）。

## 运行前后端

```bash
# 后端
uvicorn plcagent.api.app:app --reload --port 8000

# 前端（另开终端）
cd web && npm install && npm run dev    # http://localhost:5173，/api 代理到 :8000
```

可选鉴权：后端设 `PLCAGENT_API_KEY`，前端 `.env.local` 设 `VITE_API_KEY`。
基础设施凭据：复制 `config/infra.example.toml` 为 `config/infra.toml` 填写；
双环境切换用 `python scripts/switch_env.py a|b`。

## 文档导航（5 份顶层文档 + 分章源文件）

| # | 文档 | 内容 | 适用读者 |
|---|---|---|---|
| 1 | [docs/01_产品需求与验收.md](docs/01_产品需求与验收.md) | 产品定义、品牌定位、目标用户、量化验收指标、里程碑总表、对外交付边界、附录（含外部契约摘录清单） | 决策人/投资人/产品 |
| 2 | [docs/02_技术设计.md](docs/02_技术设计.md) | 架构（Vue 工作台/FastAPI/LangGraph/云 LLM）、Spec→IR→ST、Agent（24 工具清单）、仿真台、导出、数据、接口、静态检查 40 条、验证体系、互操作、运维与安全、Spec JSON Schema 与 D1 全量样例 | 开发工程师 |
| 3 | [docs/03_实施计划.md](docs/03_实施计划.md) | P0/P1/P2 周级排期、交付物、依赖与前置条件 | 项目经理/全员 |
| 4 | [docs/04_阶段验收标准.md](docs/04_阶段验收标准.md) | 每阶段验收清单（含测量方法）、验收物清单、商业交付检查表 | 验收人/QA |
| 5 | [docs/05_测试与部署.md](docs/05_测试与部署.md) | 测试分层与 CI、部署形态、发布流程、错误处置、备份 | DevOps/QA |

分章源文件在 [docs/chapters/](docs/chapters/)（按章节拆分，编号保留原文口径使交叉引用不失效；21 章为新增的 Spec Schema 与 D1 全量样例，98/99_ 前缀为修订记录、附录与新写的实施/验收/测试细则）。原始 v1.3 母本 design.md 已删除，历史版本可从 git 历史追溯。

### 维护规则

1. **chapters/ 与 5 份顶层文档内容一致**：修改分章文件后，运行 `python scripts/compose_docs.py` 重新生成顶层文档（顶层文档是生成物，不要手改）。
2. 新增内容先进 chapters/（新章节用下一个可用编号），再同步到对应顶层文档。
3. 跨文档引用一律写相对链接（如 `../02_技术设计.md`），不写章节号（章节号在拆分后不再唯一）。

## 状态

设计文档阶段（v2.2 技术栈 Python 化定稿，2026-11-08）+ P0 W1 确定性内核已实现。修订记录（v1.0 至今）见 [docs/chapters/98_revision-history.md](docs/chapters/98_revision-history.md)。
