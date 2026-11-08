# AGENTS.md — 项目规则

本文件给 AI 编码代理（与本仓库的人类贡献者）约定工作方式。改动代码前先读完。

## 项目一句话

灵枢 NeuroAxis：把工艺描述变成可运行 PLC 程序的 AI 工程 Agent。当前处于 P0 阶段，W1 确定性内核已实现（ST 子集解释器 + 虚拟时钟 + 轨迹摘要），见 `docs/chapters/99_implementation-plan.md`。

## 三条铁律（不可违反）

1. **LLM 永远不直接产出交付物**。LLM 只产出结构化 IR / Spec，ST 代码由确定性生成器生成。任何"让 LLM 直接写 ST"的实现方向都是错的。
2. **仿真台是测试台**。五道验证闸门必须全自动、不可跳过；为"方便"加绕过闸门的代码会被拒绝。
3. **真机写入永远人工闸门**。任何自动流程都不得写真机；相关 API/工具只允许"申请"，不允许"执行"。

## 分层规则

依赖方向单向，禁止反向 import：

```
api/  →  verify.py / examples/  →  st/ + trace/
storage/ infra.py → config.py（独立于语言内核）
```

- `st/` 是语言内核：**纯函数、零 IO**。禁止 import `trace/`、`api/`、任何网络/文件/数据库。
- `st/` 内禁止 `import time`、`import random`。所有时间来自注入的 `VirtualClock`，否则确定性（验收 A2）被破坏。
- `trace/` 只依赖 `st/`，不依赖上层。
- `api/` 是薄层：解析请求 → 调用核心 → 组装响应。业务逻辑不写在路由里。
- AST 节点全部 frozen dataclass（`st/ast_nodes.py`）；新增节点必须冻结。

## 数值与语义（与 matIEC 对齐，改前先查 docs/chapters/15.*）

- 整数按 C 双补码回绕溢出；REAL = IEEE754 float32（经 struct 往返）。
- 整数除法向零截断（`-7/2 = -3`）；MOD 符号跟随被除数（`-7 MOD 3 = -1`）。
- BOOL 严格：整型不可隐式转 BOOL，条件必须 BOOL。
- 无短路求值：AND/OR 两侧都求值。
- TON：上升沿开始计时、IN=FALSE 立即复位、ET 饱和。
- FOR 循环结束后变量 = stop + step；CASE 无 ELSE 时空转。
- 循环保护：FOR/WHILE 超过 100_000 次抛 `SimFault`（S09），不要移除。

改任何上述语义必须：先改 `docs/chapters/15.*` → 补测试 → 再改实现。

## 测试

- 新功能必须带测试；放 `tests/`，命名 `test_<模块>.py`。
- 需要真实基础设施（PG/Redis/RustFS）的测试打 `@pytest.mark.integration`：
  网络不可达 → skip，认证/配置错误 → fail（不许静默通过）。
- 提交前：`python -m pytest` 全绿 + `ruff check src tests` 无告警。
- 确定性红线：`plcagent verify --runs N` 的 SHA256 在改动后不变，除非改动本身就是语义变更（需更新文档与期望值）。

## 配置与密钥

- 真实凭据只在 `config/infra.toml`（已 gitignore）或 `PLCAGENT_*` 环境变量。
- **禁止**把任何真实密码/密钥写进源码、测试、docs、README。
- 新配置项：`config.py` 加默认值 → `infra.example.toml` 加模板注释 → 必要时加 env 覆盖。

## 目录约定

- 测试 → `tests/`；工具脚本 → `scripts/`；前端 → `web/`。
- 后端源码一律在 `src/plcagent/`（src 布局，保持不动）。
- 中间产物（`tmp_*`、日志、诊断输出）用完即删，不进 git。

## 文档维护

- 设计变更先进 `docs/chapters/`（新章用下一个可用编号），再跑 `python scripts/compose_docs.py` 同步顶层 5 份文档；顶层文档是生成物，不要手改。
- 跨文档引用写相对链接，不写章节号。

## 平台注意（Windows）

- Shell 是 PowerShell：多命令用 `cmd /c "a && b"` 包裹。
- 写文件优先用能控制编码的方式；文本文件一律 UTF-8 + LF，禁 UTF-16/BOM。
- 控制台中文乱码时，输出写到文件再用 ReadFile 看。

## 提交

- 遵循现有提交风格；提交前确认 `git status` 无临时文件混入。
- `config/infra.toml`、`.env*`、日志永不入库。
