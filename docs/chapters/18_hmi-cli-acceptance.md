# 18. HMI 生成、CLI 与 P1/P2 验收


### 18.1 虚拟 HMI 生成（F7）

由 Spec 机械生成（非 LLM）：模式选择器（Auto/Manual）、启停按钮、params 表单（按 R10 权限标记禁用）、报警列表（alarms 全集）、各状态机当前态显示、IO 强制面板（仿真专用）。WPF 用 DataTemplate 按类型渲染，**每类控件 ≤6 种模板**，不追求美观追求"和真 HMI 一致的操作语义"。生成 HMI 本身也进 trace（按钮点击=输入事件），保证"仿真所见=操作所得"。

### 18.2 CLI 完整命令集

```
plcagent new|edit|run|verify|export|report <project> [options]
  run     --kind generate|debug|regression [--resume <runId>]
  verify  --baseline expected/ [--mutation] [--determinism N]   # CI 入口, 退出码: 0绿/2闸门失败/3环境错误
          # --determinism N: 连跑 N 次对比 trace SHA256（验收项④/P0-5 的执行入口）
  export  --target codesys|tia|mitsubishi [--out dir]
  report  --run <runId> [--format pdf|md]
  replay  --trace x.parquet --from <scanNo>      # 快照回退重放
```

`verify` 退出码语义固化并写进 CI 文档——回归流水线只看退出码与 JUnit XML（`--junit out.xml`）。

### 18.3 P1/P2 验收（补 11 章退出条件的可测细目）

**P1（8 项）**：①PLCopen XML 导入 CODESYS 3.5 编译 0 错；②TIA Openness Worker 自动建 3 类块（FB/DB/GVL）编译 0 错（需本机 TIA V17+）；③S7 影子模式 1h 对拍：IO 一致率≥99%、差异报告可解释；④多任务解释器（2 任务优先级）确定性保持；⑤双人复核接入后审批哈希链连续；⑥虚拟 HMI 与 Spec 双向一致（改 Spec 重生成 HMI 无手工残留）；⑦服务端多用户隔离（A 用户 run 对 B 不可见）；⑧归档/恢复演练一次通过。

**P2（8 项）**：①反向解析：50 个真实老程序样本，IO 表还原准确率≥90%、控制意图可读率≥70%（专家盲评）；②RAG 引用率 100%（无引用答案不给出）；③三方言导出各自过该厂商工具编译（B/C 档人工环节除外）；④评测集扩到 50 题且 pass@5≥85%；⑤云通道脱敏审计：抓包无原始点名；⑥产品变异：删除任一 ⛨ 规则必须导致对应故障用例变红；⑦单机 20 项目连续运行 72h 无重启；⑧SDK：第三方模板插件（遵循 13 号插件契约）加载一个新 sequence 模板并过评测。

> 13/14/15/16/17/18 章与正文的交叉引用已在 v1.1 修正：1.1→14.1，4.3→13 章，5.5 覆盖门禁→G4，trace 格式→15.2。

---
