# 9. 接口


### 9.1 REST（Studio/CLI ↔ 编排层，节选）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /projects | 建工程 |
| POST | /projects/{id}/runs | 发起 Agent 闭环（kind=generate） |
| POST | /runs/{id}/gate | 闸门决定（gate, decision, note） |
| GET  | /runs/{id} | 状态与产物索引 |
| GET  | /runs/{id}/events | SSE：状态机步进/仿真进度/LLM 流式 |
| GET  | /sims/{sid}/trace?vars=a,b&from=0&to=5000 | trace 波形数据 |
| POST | /sims/{sid}/replay | 快照回放（带 seed） |
| POST | /exports | 生成导出包（需 Gate_Result approved） |

幂等：POST 带 `Idempotency-Key`；并发：同工程同时只允许一个活动 run（DB 行锁）。
