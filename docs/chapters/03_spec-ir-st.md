# 3. 工程模型：Spec → IR → ST（三段式）


### 3.1 为什么是三段而不是 LLM 直写

| 失败模式 | 直写 ST 的下场 | 三段式的解法 |
|---|---|---|
| 语法幻觉（写了不存在的指令） | 编译失败，反复来回 | IR 由 JSON Schema 卡住，非法字段根本进不了生成器 |
| 规范漂移（命名、注释、结构各项目不一样） | 不可维护 | 模板统一产出，规范是代码不是提示词 |
| 互锁遗漏 | 撞机事故 | 互锁在 Spec 里显式声明，静态检查核对完备性 |
| 不可回归 | 改一处坏三处 | IR diff 即程序 diff，测试集自动回归 |
| 审计困难 | 只有一堆聊天记录 | Spec/IR/ST 三层版本链，每次变更可追溯 |

**逃生舱**：Spec 表达不了的计算（如特殊标定公式），用 `compute` 块写受限表达式（支持算术/比较/逻辑/标准函数，禁指针禁循环），同样过静态检查。IR 表达不了的控制结构（极少数），P2 开"专家模式"允许 LLM 直写 ST 片段，但强制走同一套静态检查 + 仿真闸门 + 人工评审。

### 3.2 Spec 结构（YAML，人直接读写的唯一交付层）

```yaml
specVersion: "1.0"
project: { id: demo-d1, name: 输送线分拣D1, scanMs: 10 }

io:
  digital:
    - { name: EStop_OK,      dir: in,  addr: "%I0.0", desc: 急停回路正常(常闭) }
    - { name: Start_PB,      dir: in,  addr: "%I0.1", desc: 启动按钮 }
    - { name: Stop_PB,       dir: in,  addr: "%I0.2", desc: 停止按钮 }
    - { name: PE_Entry,      dir: in,  addr: "%I0.3", desc: 入口光电 }
    - { name: PE_SortPos,    dir: in,  addr: "%I0.4", desc: 分拣位光电 }
    - { name: Cyl1_Extended, dir: in,  addr: "%I0.5", desc: 推料缸伸出到位 }
    - { name: Cyl1_Retracted,dir: in,  addr: "%I0.6", desc: 推料缸缩回到位 }
    - { name: Conv_Run,      dir: out, addr: "%Q0.0", desc: 输送带电机 }
    - { name: Cyl1_Out,      dir: out, addr: "%Q0.1", desc: 推料电磁阀 }
    - { name: HMI_Running,   dir: out, addr: "%Q0.2", desc: 运行指示 }
    - { name: HMI_Fault,     dir: out, addr: "%Q0.3", desc: 故障指示 }

modes: [Auto, Manual]          # 手/自动
params:                        # 配方参数(可在HMI改)
  - { name: SortTimeOut, type: TIME, value: 2s, desc: 分拣动作超时 }

machines:
  - name: ConvLine             # 主状态机
    initial: Idle
    states:
      - { name: Idle,    entry: [Conv_Run:=0, Cyl1_Out:=0] }
      - { name: Running, entry: [HMI_Running:=1] }
      - { name: Sorting, entry: [Conv_Run:=0] }
      - { name: Fault,   entry: [Conv_Run:=0, Cyl1_Out:=0, HMI_Fault:=1] }
    transitions:
      - { from: Idle,    to: Running, when: "Auto AND Start_PB AND EStop_OK", prio: 1 }
      - { from: Running, to: Idle,    when: "Stop_PB OR NOT EStop_OK", prio: 1 }
      - { from: Running, to: Sorting, when: "PE_SortPos", prio: 2 }
      - { from: Sorting, to: Running, when: "Cyl1_Seq.done", prio: 1 }
      - { from: "*",     to: Fault,   when: "Cyl1_Seq.fault", prio: 0 }   # prio 0 最高

sequences:                     # 子时序(气缸往复)
  - name: Cyl1_Seq
    type: ExtendRetract        # 内置模板: 伸出→等伸出到位→缩回→等缩回到位
    bind: { out: Cyl1_Out, ext: Cyl1_Extended, ret: Cyl1_Retracted, timeout: SortTimeOut }

interlocks:                    # 互锁: 任何状态强制执行
  - { when: "NOT EStop_OK", then: [Conv_Run:=0, Cyl1_Out:=0], desc: 急停切断 }
  - { when: "mode=Manual",  then: [Conv_Run:=manual_jog],     desc: 手动点动 }

alarms:
  - { code: AL01, cond: "Cyl1_Seq.fault", text: 推料缸动作超时, level: fault }
```

**字段口径**：`io.addr` 是 IEC 地址（导出时按方言转换）；`transitions.prio` 小者优先（解决同时满足）；`from: "*"` 表示任意状态；`sequences` 只允许内置模板（P0 三种：`ExtendRetract`、`StartStopHold`、`PulseWait`），模板库随版本扩充并逐一做单元仿真——**模板是确定性的来源，宁可少而硬**。

### 3.3 IR 模型（C# 核心类型）

```csharp
// PlcAgent.Ir / Model.cs —— 与 13 号插件契约同风格，纯不可变 record
public sealed record IrProject(
    string SpecHash,                       // 溯源: 生成自哪版 Spec
    string ScanMs,
    IReadOnlyList<IrIo> Io,
    IReadOnlyList<IrMachine> Machines,
    IReadOnlyList<IrSequence> Sequences,
    IReadOnlyList<IrInterlock> Interlocks,
    IReadOnlyList<IrCompute> Compute,
    IReadOnlyList<IrAlarm> Alarms,
    IReadOnlyList<IrParam> Params);

public sealed record IrMachine(
    string Name, string InitialState,
    IReadOnlyList<IrState> States,
    IReadOnlyList<IrTransition> Transitions);

public sealed record IrTransition(
    string From, string To, IrExpr Guard, int Priority);   // Guard 是语法树,不是字符串!

public sealed record IrExpr(IrExprKind Kind, ...);          // AND/OR/NOT/CMP/VAR/LIT
```

**关键点：`Guard` 在 IR 里是语法树而非字符串**。Spec 加载时就把表达式解析成树（复用 ST 表达式解析器），这一步就消灭了"LLM 写了个奇怪表达式"的整类问题；语义校验（变量存在、类型匹配、无未定义引用）直接在树上做。

**IR 语义校验规则（P0 实现 16 条）**：

| # | 规则 | 级别 |
|---|---|---|
| V1 | 引用的 IO/参数/状态必须存在 | 错 |
| V2 | 输出点在 machines+interlocks+sequences 中有且只有一个"常态驱动者"，其余必须是互锁强制 | 错 |
| V3 | 每台设备（电机/气缸/阀）至少有一条包含其输出切断的互锁 | 错 |
| V4 | 状态机可达性：从 initial 出发所有状态可达 | 错 |
| V5 | 状态机无死锁：每个状态至少一条出边（含 "*" 边） | 错 |
| V6 | transition 同一 from 下 prio 不得重复 | 错 |
| V7 | sequence 绑定的 IO 方向正确（out→out, ext→in） | 错 |
| V8 | 表达式类型匹配（BOOL 量做逻辑运算、TIME 与 TIME 比较） | 错 |
| V9 | params 命名符合 PascalCase、io 符合 Spec 词汇表 | 警 |
| V10 | 每条 alarm 的 cond 中至少引用一个会翻转的内部信号 | 警 |
| V11 | scanMs ∈ {1,5,10,20,50} | 错 |
| V12 | 状态数 ≤ 32 / 状态机数 ≤ 8 / 互锁 ≤ 64（解释器资源上限） | 错 |
| V13 | 急停信号（EStop_OK 或等价）必须出现在至少一条互锁 | 错 |
| V14 | 输出初始值显式声明（每个 state 的 entry 覆盖其所属输出） | 警 |
| V15 | compute 块禁止循环/递归/指针/直接地址 | 错 |
| V16 | 全部 IO 已被引用（防拷贝模板留下死点） | 警 |

### 3.4 IR→ST 生成器

确定性模板生成，一个 POU 一个文件：

```
PRG_Main.st        主程序：任务调度 + 状态机 CASE + 互锁兜底
FB_Machine_<N>.st  每台状态机一个 FB（可复用、可单测）
FB_Seq_<模板>.st   时序模板库
GVL_Main.st        全局变量（IO 映射 + params）
PRG_Alarm.st       报警装配
```

生成规则示例（状态机 → ST）：

```iecst
FUNCTION_BLOCK FB_Machine_ConvLine
VAR_INPUT
    Auto        : BOOL;
    Start_PB    : BOOL;
    Stop_PB     : BOOL;
    EStop_OK    : BOOL;
    PE_SortPos  : BOOL;
    Cyl1_Seq_done  : BOOL;
    Cyl1_Seq_fault : BOOL;
END_VAR
VAR_OUTPUT
    State : INT;              // 0=Idle 1=Running 2=Sorting 3=Fault
    Conv_Run, HMI_Running, HMI_Fault : BOOL;
END_VAR
VAR
    prevState : INT := 0;
END_VAR
// ---- 状态转移: prio 升序, 先命中先走 ----
CASE State OF
  0: IF Auto AND Start_PB AND EStop_OK THEN State := 1; END_IF;
  1: IF Cyl1_Seq_fault THEN State := 3;
     ELSIF Stop_PB OR NOT EStop_OK THEN State := 0;
     ELSIF PE_SortPos THEN State := 2; END_IF;
  2: IF Cyl1_Seq_done THEN State := 1; END_IF;
  3: IF EStop_OK AND NOT Cyl1_Seq_fault THEN State := 0; END_IF;  // 故障复位条件由Spec给出
END_CASE;
// ---- entry 动作: 状态变化沿执行一次 ----
IF State <> prevState THEN
  CASE State OF
    0: Conv_Run := FALSE; Cyl1_Out := FALSE; HMI_Running := FALSE;
    1: HMI_Running := TRUE;
    2: Conv_Run := FALSE;
    3: Conv_Run := FALSE; Cyl1_Out := FALSE; HMI_Fault := TRUE;
  END_CASE;
  prevState := State;
END_IF;
END_FUNCTION_BLOCK
```

> 生成器输出保证三条：①任何输出在每个扫描周期的赋值路径可枚举（供 V2 静态核对）；②所有变量先声明后用、零隐式；③文件头带 SpecHash——**程序可反向追溯到 Spec 版本**。

### 3.5 手自动与急停的标准模板（用户最常见的三个问题，直接内置）

| 需求 | 模板行为 | Spec 表达 |
|---|---|---|
| 手/自动 | `mode` 枚举由模式开关驱动；Auto 模式下状态机生效，Manual 模式下仅 `manual_*` 互锁行生效 | `modes: [Auto, Manual]` |
| 急停 | EStop 断开 → 0 优先级 "*" 边强制进 Fault → 互锁再兜底切断全部动力输出 | V13 静态强制 |
| 故障复位 | Fault 状态的复位条件 = 各 sequence 的 fault 清除 + 复位按钮 | `faultReset` 字段 |

---
