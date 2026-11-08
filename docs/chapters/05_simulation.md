# 5. 仿真台（产品的护城河）


### 5.1 确定性模型（一切可重放的基础）

| 项 | 规则 |
|---|---|
| 时基 | 虚拟时钟 `simTime = scanNo × scanMs`，与墙钟解耦；实时模式 1×，加速模式尽力跑 |
| 扫描 | 读输入映像 → 执行任务（单线程，固定顺序）→ 写输出映像 → trace 记录 |
| 植物步长 | 虚拟设备固定 1ms 步长积分，每个扫描周期内步进 scanMs 次 |
| 随机 | 仅传感器噪声用随机，种子 = `hash(SpecHash, RunId, caseId)` |
| 通信 | P0 无通信延迟模拟（进程内直连映像）；P1 加可配延迟/丢包注入 |
| 快照 | 每 100 扫描可快照（全变量+植物状态），支持"断点回退到第 N 扫描重放" |

**验收 A2 硬指标**：同 Spec+同用例跑 1000 次，trace SHA256 全等。这条做不到，覆盖率、回归、Debugger 全部失效——它是第一优先级实现项。

### 5.2 软 PLC 解释器（子集语义）

支持集合（= 3.1 生成器会产出的全部 + 手写逃生舱允许的）：

| 类别 | 支持 | 明确不支持 |
|---|---|---|
| 类型 | BOOL/BYTE/INT/DINT/UINT/UDINT/REAL/TIME/STRING/ARRAY[定长] | 指针/REF、联合、OOP(METHOD/PROPERTY) |
| 语句 | 赋值/IF/CASE/FOR/WHILE/REPEAT/RETURN | GOTO |
| 标准FB | TON/TOF/TP/CTU/CTD/CTUD/R_TRIG/F_TRIG/SR/RS/PID | RTOS 相关、文件、SOE |
| 任务 | 单任务循环扫描（P1 加多任务优先级） | 事件任务、中断 |

扫描内执行语义与 IEC 61131-3 对齐的点：TON 基于虚拟时钟累计（非墙钟）；CASE 落空不报错但插桩计数（覆盖率用）；变量无显式初始化时 BOOL=FALSE/数值=0 并打 V14 警告。

解释器插桩四件套（为覆盖率与 trace 服务，这是"为什么不直接用 OpenPLC"的根因）：

```csharp
public interface IInstrumentedRunner
{
    void OnBeforeStatement(int stmtId);          // 分支/语句覆盖打点
    void OnVarWrite(string var, IrValue v);      // trace
    void OnVarRead(string var, IrValue v);
    int  CurrentScan { get; }                    // 断点/回退用
}
```

### 5.3 虚拟设备库（P0 12 种，每种 ≤200 行 + 单元测试）

| 元件 | 输入 | 输出 | 模型 | 关键参数 |
|---|---|---|---|---|
| 电机(M带减速器) | Run | running, speed, pos | 一阶速度环 τ=200ms | τ, 额定转速 |
| 输送线 | motor_on | pe_out(光电), item_at(x) | 质点匀速+队列 | 长度, 速度, 间距 |
| 气缸 | valve_out | extended, retracted | 双稳态+匀速行程 | 行程ms, 磁开位置 |
| 泵 | run | flow | 线性流量 | Qmax |
| 阀(开关) | open_cmd | opened, closed, pos | 同气缸 | 行程ms |
| 阀(调节) | opening% | flow | 快开/线性特性 | Cv, 特性 |
| 液位罐 | in_flow, out_flow | level, hi, lo, hh, ll | dv/dt=(Qi-Qo)/A | 面积A, 量程 |
| 压力/温度变送 | 物理量 | 4-20mA 数字值 | 量程线性+噪声 | 量程, 噪声σ |
| 光电/接近 | 物理遮挡 | bool | 阈值+回差 | 回差 |
| 编码器 | 轴角 | count | 正交计数 | PPR |
| 加热器 | pwm | temp | 一阶热容 | C, 散热系数 |
| 计数品 | 检测沿 | count | 事件 | — |

**元件接口**：

```csharp
public interface IPlantComponent
{
    void Bind(IoImage io, PlantParams p);   // 与 Spec io.addr 映射
    void Step(double dt);                   // dt=1ms, 读输出映像→物理演化→写输入映像
    void Inject(Fault f);                   // 故障注入: 卡死/漂移/断线/恒值
    PlantSnapshot Snapshot();
}
```

**故障注入矩阵（测试用例的常客）**：卡死在位 / 传感器恒0恒1 / 漂移+10% / 断线(质量位Bad) / 延迟响应 / 噪声增大 / 急停触发 / 扫描超时注入。

### 5.4 测试 DSL 与断言

> **用例与 plant 参数必须对齐**：`expect` 里写死的时间窗（如 `afterMs: 3500`）隐含了「气缸行程 ≈ 2s + 磁开响应」的 plant 参数假设。**用例、Spec 的 `SortTimeOut`、`plant/params.yaml` 三处必须同源校验**——Runner 启动时核对：用例中出现的最大 `afterMs + withinMs` 不得 ≥ `SortTimeOut`（否则正常循环必触发超时报警）；plant 行程时间改动后，黄金基线 trace 必须重录。这条不做，评测集会因参数漂移「无差别变红」，烧掉对确定性的一切信任。

```yaml
suite: demo-d1
cases:
  - id: normal_cycle
    desc: 正常分拣一循环
    init: { EStop_OK: true, Cyl1_Retracted: true }
    steps:
      - { set: { Start_PB: true } }
      - { expect: { Conv_Run: true, withinMs: 100 } }
      - { set: { Start_PB: false } }
      - { set: { PE_SortPos: true } }           # 或用 plant 驱动: - { drive: conveyor.push_item() }
      - { expect: { Cyl1_Out: true, withinMs: 200 } }
      - { expect: { Cyl1_Out: false, afterMs: 3500, withinMs: 500 } }  # 伸出到位后缩回
  - id: estop_mid_cycle
    desc: 分拣中急停
    steps:
      - { set: { PE_SortPos: true } }
      - { set: { EStop_OK: false } }
      - { expect: { Conv_Run: false, Cyl1_Out: false, withinMs: 50 } }  # 5个扫描内
      - { assert_never: { expr: "Conv_Run AND Cyl1_Out", whole_case: true } }
  - id: timeout_fault
    desc: 气缸超时故障
    inject: { Cyl1_Extended: stuck_0 }
    steps:
      - { set: { Start_PB: true } }
      - { set: { PE_SortPos: true } }
      - { expect: { Cyl1_Seq_fault: true, afterMs: 2500, withinMs: 1000 } }  # 超过 SortTimeOut=2s 后报 fault
      - { expect: { HMI_Fault: true, withinMs: 100 } }
asserts:                                       # 全局不变式(每个用例都查)
  - { expr: "NOT (Conv_Run AND State=3)", desc: 故障态不得运行 }
coverage_gate: { statement: 100, branch: 90, state: 100, transition: 100, io_write: 100 }
```

**断言类型**：`expect`（点值+时间窗）/ `assert_never`（不变式）/ `expect_seq`（时序次序）/ `coverage_gate`（门禁）。`drive:` 语法直接调用虚拟设备行为（推一件料），比手工拨 IO 自然。

**DSL 步骤文法（Runner 实现口径）**：

| 关键字 | 参数 | 语义 |
|---|---|---|
| `set` | `{信号: 值}` | 本扫描起点强制输入映像为指定值（仅允许 dir=in 的点） |
| `expect` | 点值 + `withinMs`（从此刻起算的最大等待）/ `afterMs`（从此刻起先等 N ms 再开始判） | 在窗口内采样断言，超窗即失败 |
| `assert_never` | `expr` + `whole_case` | 不变式：整个用例期间表达式恒假，任一扫描为真即失败 |
| `expect_seq` | `[{signal, value}...]` | 时序次序：信号按列出顺序先后翻转（允许夹带其他事件） |
| `drive` | `设备.方法(参数)` | 调用虚拟设备行为（如 `conveyor.push_item()` 推一件料进队列） |
| `inject` | `{信号: 故障类型}` | 故障注入：`stuck_0 / stuck_1 / drift_+10% / bad(断线) / delay_ms / noisy` |
| `init` | `{信号: 值}` | 用例开始前的输入映像初值 |

`withinMs`/`afterMs` 的起点统一为"上一步骤完成的虚拟时刻"；时间窗校验使用虚拟时钟而非墙钟（确定性要求）。

### 5.5 覆盖率门禁

| 维度 | 来源 | P0 门禁 |
|---|---|---|
| 语句/分支 | 解释器插桩 | 100% / 90% |
| 状态/转移 | IR 状态机执行记录 | 100% / 100%（生成代码天然可全测，测不全说明用例缺） |
| IO 写覆盖 | OnVarWrite | 每个 out 点至少一次 TRUE 和一次 FALSE |
| 故障注入 | 用例标注 | V3 互锁清单每条至少一个用例触发 |
