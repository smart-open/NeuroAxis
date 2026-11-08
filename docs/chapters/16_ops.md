# 16. 运维生产化


### 16.1 容量与资源模型（以 D1 规模为基准，P0 机器 i5/16G）

| 项 | 估算 | 依据 |
|---|---|---|
| trace 体积 | 32 IO × 10ms 扫描 × 10min 用例 ≈ 100MB/用例（Parquet 列存后 ~30MB） | 全量记录仅变化信号（游程编码）；扫描周期以 16.2 配置 `sim.scanMs: 10` 为准 |
| 单项目磁盘 | Spec+IR+ST+trace+报告 ≈ 200MB；20 项目/月 ≈ 4GB/月 | 归档策略见 16.5 |
| SimHost 内存 | ≤300MB（D1 规模）；上限配额 2GB 超限强杀重启 | 每实例隔离，泄漏不拖 Web/API |
| 仿真吞吐 | ≥20× 实时（1.3 验收）；实际≈解释器 50万语句/s 量级 | 插桩关闭时再快 3~5 倍 |
| LLM 成本 | 4.5 节预算：单 run ≤60 调用 / ≤¥5 | llm_call 表按日汇总告警 |

### 16.2 配置项清单（`plcagent.json`，全部有默认值、带 schema 校验）

```jsonc
{
  "sim":  { "scanMs": 10, "speedX": "max", "traceLevels": ["io_write","state_change"],
            "snapshotEvery": 100, "simHostInstances": 2, "memCapMB": 2048 },
  "llm":  { "endpoint": "https://api.deepseek.com/v1", "model": "deepseek-chat",
            "fallbackEndpoints": ["https://dashscope.aliyuncs.com/compatible-mode/v1"],
            "temperature": 0.2, "maxCallsPerRun": 60,
            "budgetCnyPerRun": 5.0, "redactCloud": true },
  "gate": { "maxDebugRounds": 5, "maxDesignRounds": 3, "mutationKillRate": 0.8 },
  "export": { "matiecPath": "./vendor/matiec/bin/iec2c", "enableSecondaryCompile": false },
  "rules": { "disable": [], "warnAsError": false }   // ⛨ 规则写进来直接拒启动
}
```

### 16.3 错误码与故障恢复（Web 工作台状态条 + 日志双呈现）

| 码 | 场景 | 恢复策略 |
|---|---|---|
| E-SIM-CRASH | SimHost 崩溃/OOM | 自动重启实例 + 从快照续跑；同一 run 崩 ≥3 次判 fail |
| E-LLM-TIMEOUT | 单次 LLM >60s | 重试 2 次（指数退避）→ 切 fallbackEndpoints 备用供应商 → 降级规则引擎或转人工 |
| E-LLM-BUDGET | 预算熔断 | run 挂起转人工，已有产物保留 |
| E-GATE-TIMEOUT | 闸门无人响应 >72h | run 挂起+提醒；不自动通过（安全闸门永不超时通过） |
| E-SPEC-CONFLICT | 并发编辑 | 行锁拒绝第二个 run（9.1），提示刷新 |
| E-TRACE-MISS | 回放哈希不符 | 拒绝并提示重新生成（15.2） |
| E-EXPORT-FAIL | 方言映射/编译失败 | 产物不入库，报具体规则码 |
| E-REDIS-DOWN | Redis 不可用 | SSE 降级轮询 + 队列暂停；run 状态以 PG 为准，恢复自动续跑 |
| E-RUSTFS-DOWN | 对象存储不可用 | 新仿真挂起不入库；历史 trace 从只读缓存提供 |

### 16.4 并发与队列

同工程单活动 run（行锁）；SimHost 实例池默认 2（一个交互一个 CI）；LLM 网关令牌桶 10 req/s，云 API 并发 4（可配）。

### 16.5 备份、归档与升级

| 项 | 策略 |
|---|---|
| DB | 每日 pg_dump + WAL 归档，RPO≤5min；恢复演练每季度（沿用 13 号 7.7 口径） |
| trace/产物 | RustFS（S3 兼容）生命周期：90 天转冷存，基线 trace 永久 |
| 产品升级 | schema 迁移只增不改（Alembic）；旧 trace 因 meta 含 productVersion 永可读 |
| 兼容承诺 | Spec/IR schema 大版本（specVersion 1.x 向后兼容）；Prompt/模板版本化，可一键回退（14.2） |
| 卸载 | 数据全在用户目录与自建 PG，无隐藏注册表项 |

**基础服务可用性**：Redis 宕机 → SSE 实时推送降级为前端轮询、任务队列暂停（已入库 run 不丢，重启恢复）；RustFS 宕机 → 新仿真不可落盘（挂起），历史 trace 可从本地缓存只读；两者均为 P0 单机部署，P1 起按 13 号 7.7 口径纳入备份演练。Redis 数据可丢——全部状态的事实来源在 PG（8.3）。
