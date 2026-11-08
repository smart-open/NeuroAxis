# 6. 诊断与修复闭环（最值钱的一段）


Simulate 失败 → `trace.summarize` → 4.4 规则归因 → `ir.patch` 出 Spec diff 提案 → Orchestrator 校验（V1~V16）→ 重新生成 → 回归**全量**用例（防修好 A 坏 B）。5 轮不收敛升级人工，并附前几轮归因对比（避免原地打转——连续两轮同类归因直接升级）。
