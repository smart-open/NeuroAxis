# 测试与部署

## 1. 测试分层（汇总自 14.2，加执行细则）

| 层 | 内容 | 频率 | 时长预算 | 失败处置 |
|---|---|---|---|---|
| 单元 | 解释器每 FB 语义、元件模型积分、规则引擎（每条规则 ≥3 用例：命中/不命中/边界，13.5） | 每提交 | <2 min | 阻断合并 |
| 确定性 | D1 跑 1000 次哈希全等（5.1 验收硬指标） | 每日 | <10 min | 冻结发版，报产品 bug（D8） |
| 评测集 | 20 题黄金集全流程 | 每日 + Prompt/模板变更必跑 | <30 min | 退化 >5pp 冻结发版，回退 Prompt/模板版本 |
| 端到端 | D1/D2/D3 三样例 `plcagent verify --baseline expected/` | 每提交 | <5 min | 阻断合并 |
| 兼容 | matIEC 编译导出 ST；PLCopen XML round-trip | 每日 | <5 min | 阻断发版 |
| 规则变异 | 删除安全规则 → 故障注入集必须有用例从绿变红 | 变更规则时 | <10 min | 规则不得合入 |

**CI 入口**：`plcagent verify --baseline expected/ --mutation --junit out.xml`；退出码语义（18.2）：`0`=绿、`2`=闸门失败、`3`=环境错误。

## 2. 部署形态

| 形态 | 部署物 | 安装方式 | 目标环境 |
|---|---|---|---|
| P0 服务器 | FastAPI + LangGraph（Web 工作台 API + 编排）+ PostgreSQL 16 + RustFS + Redis + `plcagent` PyPI 包 | Docker Compose 单机部署（Postgres/RustFS/Redis/API/SimHost 五容器，镜像摘要锁定） | 一台 i5/16G 服务器；工程师浏览器访问；LLM 走云 API（key 只经环境变量注入服务端） |
| P1 扩展 | + RAG 知识库运营（pgvector 已内置于 PG） | 同上，可加副本 | 多用户 RBAC；PG 每日 pg_dump + WAL 归档（16.5）；RustFS 数据纳入备份 |
| 离线场景 | 暂不承诺 | — | 本地模型通道 P2 再评估（2.3 章）；强离线客户先引导走临时云通道或排除交付 |

## 3. 发布流程与兼容承诺（汇总自 16.5）

1. 版本号：SemVer；schema 迁移只增不改（Alembic）。
2. 旧 trace 因 sidecar 含 productVersion 永可读（15.2 四哈希校验）。
3. Prompt/模板均版本化；评测集退化可一键回退（14.2）。
4. 发布前置检查：CI 全绿 + 确定性当日通过 + 评测集无退化。
5. 商业发布前逐行勾掉《04_阶段验收标准》第 4 节（签名/SBOM/许可/登记表）。

## 4. 运行期错误处置（汇总自 16.3）

| 码 | 场景 | 恢复策略 |
|---|---|---|
| E-SIM-CRASH | SimHost 崩溃/OOM | 自动重启 + 快照续跑；同 run 崩 ≥3 次判 fail |
| E-LLM-TIMEOUT | 单次 LLM >60s | 重试 2 次（指数退避）→ 切备用供应商（16.2 fallbackEndpoints）→ 降级规则引擎或转人工 |
| E-LLM-BUDGET | 预算熔断 | run 挂起转人工，产物保留 |
| E-GATE-TIMEOUT | 闸门 >72h 无响应 | 挂起+提醒；**安全闸门永不超时自动通过** |
| E-SPEC-CONFLICT | 并发编辑 | 行锁拒绝第二个 run |
| E-TRACE-MISS | 回放哈希不符 | 拒绝回放，提示重新生成 |
| E-EXPORT-FAIL | 方言映射/编译失败 | 产物不入库，报具体规则码 |

## 5. 备份与容量

- DB：每日 pg_dump + WAL 归档，RPO≤5min；恢复演练每季度。
- trace/产物：RustFS（S3 兼容）生命周期 90 天转冷存，黄金基线永久。
- 磁盘：单项目 ≈200MB，20 项目/月 ≈4GB（16.1 容量模型）。
- SimHost 内存配额 2GB 超限强杀重启。
