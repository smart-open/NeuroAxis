# 9. 接口


### 9.1 REST（Web 工作台/CLI ↔ 编排层，节选）

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

推送口径：`/runs/{id}/events` 用 **SSE**（与 2.3 选型一致，SignalR 为备选）；SSE 断线重连约定 `Last-Event-ID` 头，服务端从对应 run_step 序号续推。

### 9.2 认证与权限（P0 最小实现，P1 接 13 号 RBAC）

| 项 | P0 | P1 |
|---|---|---|
| 认证 | 单管理员账号 + 用户名密码（bcrypt 存储）+ HttpOnly Session Cookie；全程 HTTPS（反向代理终结 TLS） | 对接 13 号 RBAC/审计，双闸门双人复核 |
| 授权 | 所有写操作（run/gate/export）要求登录；闸门操作记录 `by_user` | 角色权限码（Viewer/Engineer/Approver） |
| API 安全 | 同源限制 + CSRF token（表单提交）；SSE 走同一会话鉴权 | 13 号审计哈希链覆盖全部 API 写操作 |
| CLI | 本机 localhost 访问 API，token 存用户目录（0600） | token 过期与刷新 |
