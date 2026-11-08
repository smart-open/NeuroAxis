# 15. 互操作规范（跨实现一致性的合同）


### 15.1 ST 子集精确语义（解释器与 matIEC 差分测试的判定表）

未列出的按 IEC 61131-3:2013 默认；**任何一条解释器与 matIEC 观察行为不一致，以 IEC 标准为准修解释器，并加差分用例**。

| 语义点 | 本产品口径 |
|---|---|
| 整数溢出 | DINT/INT 运算按目标平台回绕（与 matIEC/C 编译一致）；生成器避免产生可溢出表达式（常量折叠时检查） |
| REAL 精度 | REAL=IEEE754 单精度；生成器比较一律用容差（S14 提示） |
| 布尔短路 | ST 逻辑运算**不保证短路**（标准未定），生成器禁在 `X AND f(X)` 依赖求值序；解释器按全求值实现 |
| `:=` 求值序 | 右侧全求值后赋左侧；多输出 FB 调用原子生效 |
| TON 语义 | IN 上升开始累计，IN=FALSE 立即清零；ET 单调基于虚拟时钟；同实例重复调用取首调用为准（S17 禁止复用） |
| TIME 字面量 | 最小分辨率 1ms；T#+浮点秒向下取整 ms |
| FOR 循环 | 循环变量终值后为 `to` 值+步长（IEC 定义），差分用例覆盖 |
| CASE 落空 | 无 else 执行空，插桩计数进分支覆盖 |
| 数组越界 | 运行时检查：解释器抛 SimFault 并判用例失败（比 C 的未定义行为更严格，故意收紧——生成器已由 S04 阻断，运行时越界即产品 bug） |
| 字符串 | 定长 80，超长截断+W 警告 |

### 15.2 trace Parquet schema（对内存储、对外回放的唯一格式）

```
trace.parquet
  scan_no      int64      扫描号
  t_ms         int64      虚拟时刻 = scan_no * scanMs
  kind         enum       io_write / io_read / state_change / stmt_cov / fault / snapshot
  var          string     信号名（stmt_cov 行为规则 id）
  value        binary     变量值（类型由 io 表 sidecar 确定）
```
sidecar `trace.meta.json`：`{specHash, irHash, stHash, seed, scanMs, productVersion, suiteHash}`——**回放时先验四哈希，任一不符拒绝回放**。保留策略：run 级 90 天、基线级永久（与 8.2 一致，磁盘预算见 16.1）。

### 15.3 方言地址映射（导出器共用表）

| 本产品（IEC 风格） | CODESYS/PLCopen | 三菱 FX5U（导出注释用） | S7 TIA（B 档映射） |
|---|---|---|---|
| %I0.x | %IX0.x（byte.bit） | X0~X377（八进制!） | I0.x |
| %Q0.x | %QX0.x | Y0~ | Q0.x |
| %MW0 | %MW0（WORD） | D0（word 区） | MW0→DB 建议映射为全局 DB |
| %MD0 | %MD0 | D 偶址对（REAL 需对齐） | MD0 |

三菱八进制地址转换在导出器内实现并单测（0.8→1.0 进位是常见事故，专列 2 个差分用例）。映射错误 = E 级导出失败，不给"大概能用"的产物。

### 15.4 matIEC 调用协议

```
子进程: matiec/bin/iec2c -f -p -l <合并后的单文件.st> -o <outdir>
退出码: 0=成功; >0=失败, stderr 逐行 "文件:行:列: 错误文本"
映射:   解析 stderr → 转 {rule:S01, file, line, col, message} 原样进报告
超时:   30s 强杀, 判 G1 失败并注明"参考编译器超时"
边界:   仅作校验, 不取其 C 产物执行; 独立目录+独立进程(LGPL 边界, A8)
```

### 15.5 PLCopen XML 元素映射（F8 的验收口径）

| IR | PLCopen TC6 v2.0 |
|---|---|
| IrIo | `<interface><localVars>` + `<addData>` 留地址注释 |
| IrMachine | 一个 `<pou name="FB_Machine_X" pouType="functionBlock">`，状态机 CASE 体进 `<body><ST>` |
| IrParam | `<globalVars>`（constant=true） |
| 互锁 | PRG_Main 末尾赋值段 |
| round-trip | 本产品导出→CODESYS 导入编译通过 为验收；导入方向（反向解析 F10）P2 单列，不承诺双向无损 |
