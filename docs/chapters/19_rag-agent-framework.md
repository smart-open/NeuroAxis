# 19. RAG 知识库与 Agent 框架生产化（v1.2）


### 19.1 知识库三层语料与摄取管线

A6 的"三层"落到工程口径：

| 层 | 语料 | 来源 | 更新方式 | 切片策略 |
|---|---|---|---|---|
| K1 规范库 | IEC 61131-3 要点自编摘要、本产品语义口径（15.1）、编码规范 | 官方标准**不入库分发**（版权），入库的是自编对照笔记 + 本产品语义表 | 随版本发布，只读 | 按语义点一节一片，`docId` 固定（语义表变更 → 哈希变更 → 缓存失效） |
| K2 厂商库 | CODESYS/三菱/西门子公开手册章节、方言差异表 | 用户自备 PDF 导入（工具不分发手册） | 增量摄取 | 按 PDF 二级标题切片 300~800 字；表格转 markdown 保结构 |
| K3 项目库 | 已批准工程的 Spec/IR/最终 ST/失败案例归因（脱敏后） | Gate_Result 通过时自动入库 | 追加 | Spec 整片 + 归因报告整片；**只入"人批准过"的版本** |

**摄取管线**（LlamaIndex 仅用于此段，检索走自有栈）：

```
导入 → 解析(PDF/MD/CSV) → 清洗(去页眉页脚/表格结构化) → 切片
     → 元数据 {layer, vendor, docId, section, version, contentHash}
     → embedding(云 API embedding, 模型版本记元数据) → pgvector
     → FTS 索引(tsvector) 同步构建
```

每片必须带 `contentHash`：文档重导时旧片失效（软删），引用回链指向新版本——**回答里的引用必须可点开原文**，这是审计要求不是体验优化。

### 19.1a 向量数据库选型（结论：pgvector）

| 候选 | 优势 | 劣势 | 适配度 |
|---|---|---|---|
| **pgvector（PG 16 内）** | HNSW 索引；embedding 与 kb 元数据**同库事务一致**；FTS 同库做混合检索（RRF）；零新增运维面 | 百万级以上写入吞吐弱于专用库 | ★★★★★ 选定 |
| Qdrant | Rust 单二进制，过滤检索强 | 多一个有状态服务（备份/升级/监控），元数据跨库一致性问题 | ★★ 备选 |
| Milvus | 十亿级、分布式 | 架构重（etcd/MinIO），本项目量级严重过配 | ★ |
| Chroma | 上手快 | 生产化成熟度弱 | ★ |
| Weaviate | 内置混合检索 | 多一个服务面，中文语料实践少 | ★★ |

**决定性理由是规模与一致性，不是性能跑分**：① 三层语料合计预估 ≤ 百万片，HNSW + vector(1024) 在 16G 单机 P99 < 20ms，余量 10 倍以上；② 「换模型全量重嵌、旧片软删、引用回链」的审计红线靠同库事务兜底，跨库做不到；③ pgvector + FTS + RRF 同一条 SQL 完成，19.2 无需跨库编排。**逃生舱**：语料 >500 万片或过滤检索占比失控时切 Qdrant——检索层已抽象（RRF 融合在应用侧），切换只动一个模块。

### 19.2 检索与生成（混合检索 + 强制引用）

```mermaid
flowchart LR
  Q[查询+角色上下文] --> RW[查询改写\n领域词表+同义展开]
  RW --> V[pgvector top20] & F[FTS top20]
  V & F --> RRF[RRF 融合 top10]
  RRF --> RR[重排 top5\nLLM listwise（P2）]
  RR --> FILT[过滤: layer 权限+版本匹配]
  FILT --> CTX[4.5 上下文装配\n知识段≤2k 带引用]
```

**强制引用规则**（写进系统 Prompt 与输出 Schema）：凡陈述厂商行为/标准语义的句子必须带 `[docId#section]`；引用不存在的 docId → 结构校验失败重试；P2 验收"引用率 100%"（18.3）即此口径。检索无命中时明确答"知识库无依据"，**禁止用参数知识补厂商事实**——这是与通用聊天机器人的本质区别。

### 19.3 kb 相关表（补 8.2 DDL）

```sql
CREATE TABLE kb_doc (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  layer       text NOT NULL,               -- k1/k2/k3
  vendor      text,                        -- k2: codesys/mitsubishi/siemens
  title       text NOT NULL,
  source_uri  text,                        -- k3 指向 run/工程
  version     int  NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE kb_chunk (
  id          bigserial PRIMARY KEY,
  doc_id      uuid NOT NULL REFERENCES kb_doc(id),
  section     text NOT NULL,               -- 引用回链锚点
  content     text NOT NULL,
  content_hash text NOT NULL,
  embedding   vector(1024) NOT NULL,
  fts         tsvector NOT NULL,
  active      boolean NOT NULL DEFAULT true,  -- 重导后旧片置 false
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX kb_chunk_vec ON kb_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX kb_chunk_fts ON kb_chunk USING gin (fts);
CREATE INDEX kb_chunk_doc ON kb_chunk (doc_id) WHERE active;
```

召回评测：20 个固定查询集（如"TON 与 TP 区别""FX5U 八进制地址""气缸超时归因"）跑 recall@5 ≥ 0.8 进 CI（每日），退化即冻结切片策略变更。embedding 模型版本记入 kb_chunk 元数据——**换模型必须全量重嵌**，杜绝新旧向量混检。

### 19.4 Agent 编排：LangGraph（P0 即采用）

**为什么 P0 即上**：主技术栈为 Python（0.3/2.3），LangGraph 的 checkpoint 持久化、`interrupt` 人闸、时间旅行回放与 4.2 状态机语义同构——Debug 归因子图（4.4 规则 8 条 + 反事实回放）、知识库问答子图（19.2）、错误排障子图直接建在同一张图上，不必自研编排。**红线不变**：G1~G5 闸门是图外硬编码服务，图节点只能"请求进入下一节点"，闸门永不交给框架。

**集成架构**（进程边界与 2.2 一致）：

```mermaid
flowchart LR
  ORCH[LangGraph 编排\n状态机+闸门+权限] -->|代理调用| LG[LangGraph 子图
Debug 归因/知识库问答/排障]
  
  LG --> CKPT[(checkpoint\nPostgreSQL)]
  ORCH --> DB2[(run/run_step)]
```

| 设计点 | 口径 |
|---|---|
| 节点映射 | 4.2 六节点 = LangGraph 图六节点；Debug 归因 4.4 = 独立子图；G1~G5 闸门仍是**图外硬编码服务**，LangGraph 只能"请求进入下一节点"，闸门永不交给框架 |
| checkpoint | LangGraph checkpointer 落 PostgreSQL（独立 schema `lg_`），与 run_step 双写对账；崩溃恢复以 run_step 为准 |
| 中断 | Gate_Spec/Gate_Result 用 LangGraph `interrupt` 实现，恢复由闸门服务决定写入后 resume |
| 权限 | 图节点经工具网关访问工具，无 DB 直连凭据、无文件系统写、无网络出口——**框架是员工，不是老板** |
| 等价回归 | 切换前跑：评测集 20 题在两实现各跑 3 次，节点序列与产物哈希全等才允许切换；配置 `agent.engine: builtin\|langgraph` 可随时回退 |
| 可观测 | LangGraph 每节点进出事件记 run_step；图结构导出 mermaid 附证据包 |

**LlamaIndex 边界**（19.1 已述）：只用于摄取 pipeline，不采用其索引/检索闭包——检索、存储、引用回链全部走自有 pgvector 栈，避免双框架维护。

**自研状态机保留为回退**：`agent.engine: builtin` 一键回退；等价回归集（评测集 20 题 × 两实现节点序列与产物哈希全等）作为引擎切换闸门。LangGraph 锁定版本，升级须过回归集并记录于 kb_doc。

### 19.5 新增风险（并入 12 章）

| 风险 | 对策 |
|---|---|
| LangGraph 版本演进快，P1 引入即被 Breaking Change 打击 | 锁版本 + 等价回归集 + `agent.engine` 回退开关 |
| RAG 语料版权（厂商手册随产品分发） | 工具只提供导入能力，手册由用户自备；K1 不入标准原文 |
| 双写（run_step 与 lg checkpoint）漂移 | 对账任务每日跑，漂移即告警并以 run_step 为准修 checkpoint |

---
