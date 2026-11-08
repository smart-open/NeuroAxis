# 21. Spec JSON Schema 与 D1 样例工程全量文件

> 拆分时补写。3.2 只给了 YAML 示例，本节给出 Schema 定义与 D1 样例的全部配套文件——这是 W2/W4 的直接开工对象。

## 21.1 spec.schema.json（草案，与 V1~V16 配合使用）

```jsonc
{
  "$schema": "http://json-schema.org/draft-2020-12/schema",
  "title": "NeuroAxis Spec",
  "type": "object",
  "required": ["specVersion", "project", "io", "machines"],
  "properties": {
    "specVersion": { "const": "1.0" },
    "project": {
      "type": "object",
      "required": ["id", "name", "scanMs"],
      "properties": {
        "id":   { "type": "string", "pattern": "^[a-z][a-z0-9-]*$" },
        "name": { "type": "string", "minLength": 1 },
        "scanMs": { "enum": [1, 5, 10, 20, 50] }        // =V11
      }
    },
    "io": {
      "type": "object",
      "properties": {
        "digital":  { "$ref": "#/$defs/ioList" },
        "analog":   { "$ref": "#/$defs/ioList" }
      }
    },
    "modes":  { "type": "array", "items": { "type": "string" }, "maxItems": 4 },
    "params": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "type", "value"],
        "properties": {
          "name":  { "type": "string", "pattern": "^[A-Z][A-Za-z0-9]*$" },  // PascalCase =V9
          "type":  { "enum": ["BOOL", "INT", "DINT", "REAL", "TIME"] },
          "value": {},
          "desc":  { "type": "string" },
          "hmiWritable": { "type": "boolean", "default": true }   // R10 权限标记
        }
      }
    },
    "machines": {
      "type": "array", "maxItems": 8,                           // =V12
      "items": {
        "type": "object",
        "required": ["name", "initial", "states", "transitions"],
        "properties": {
          "name": { "type": "string" },
          "initial": { "type": "string" },
          "states": {
            "type": "array", "maxItems": 32,                    // =V12
            "items": {
              "type": "object",
              "required": ["name"],
              "properties": {
                "name":  { "type": "string" },
                "entry": { "type": "array", "items": { "$ref": "#/$defs/action" } }
              }
            }
          },
          "transitions": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["from", "to", "when", "prio"],
              "properties": {
                "from": { "type": "string" },     // "*" 允许
                "to":   { "type": "string" },
                "when": { "type": "string", "description": "表达式语法见 3.3；加载时解析成 IrExpr 语法树" },
                "prio": { "type": "integer", "minimum": 0 }
              }
            }
          }
        }
      }
    },
    "sequences": {
      "type": "array", "maxItems": 16,
      "items": {
        "type": "object",
        "required": ["name", "type", "bind"],
        "properties": {
          "name": { "type": "string" },
          "type": { "enum": ["ExtendRetract", "StartStopHold", "PulseWait"] },  // P0 三种内置模板
          "bind": {
            "type": "object",
            "properties": {
              "out": { "type": "string" }, "ext": { "type": "string" },
              "ret": { "type": "string" }, "timeout": { "type": "string" }
            }
          }
        }
      }
    },
    "interlocks": {
      "type": "array", "maxItems": 64,                          // =V12
      "items": {
        "type": "object",
        "required": ["when", "then"],
        "properties": {
          "when": { "type": "string" },
          "then": { "type": "array", "items": { "$ref": "#/$defs/action" } },
          "manualOnly": { "type": "boolean", "default": false },  // 仅手动模式生效（3.5）
          "desc": { "type": "string" }
        }
      }
    },
    "compute": {                                              // 逃生舱 =V15
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "expr"],
        "properties": {
          "name": { "type": "string" },
          "expr": { "type": "string", "description": "受限表达式：算术/比较/逻辑/标准函数；禁循环/递归/指针/直接地址" }
        }
      }
    },
    "alarms": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code", "cond", "text", "level"],
        "properties": {
          "code":  { "type": "string", "pattern": "^AL[0-9]{2,4}$" },
          "cond":  { "type": "string" },
          "text":  { "type": "string" },
          "level": { "enum": ["info", "warn", "fault"] }
        }
      }
    },
    "faultReset": {                                           // 3.5 故障复位
      "type": "object",
      "properties": {
        "signal": { "type": "string", "description": "复位按钮输入点" },
        "cond":   { "type": "string", "description": "附加复位条件（如各 sequence fault 已清除）" }
      }
    }
  },
  "$defs": {
    "ioList": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "dir", "addr"],
        "properties": {
          "name": { "type": "string", "pattern": "^[A-Z][A-Za-z0-9_]*$" },
          "dir":  { "enum": ["in", "out"] },
          "addr": { "type": "string", "pattern": "^%(I|Q|IW|QW|ID|QD)[0-9]+(\\.[0-9])?$" },
          "type": { "enum": ["BOOL", "INT", "DINT", "REAL"], "default": "BOOL" },
          "desc": { "type": "string" }
        }
      }
    },
    "action": {
      "type": "string",
      "pattern": "^[A-Z][A-Za-z0-9_]*(:=(0|1|TRUE|FALSE|[A-Za-z0-9_.]+))?$",
      "description": "形如 Var:=值 的赋值字符串；加载时解析校验"
    }
  }
}
```

Schema 表达不了的语义规则（V1~V16 中需代码实现的）由 `spec.validate` 在加载后执行；两者分工：**Schema 管结构，校验器管语义**。

## 21.2 D1 样例工程全量文件

### plant/params.yaml（D1，与 5.4 用例时间窗对齐）

```yaml
# D1 输送线分拣 —— 虚拟设备参数
# 修改本文件后必须重录 expected/ 黄金基线（5.4 三处同源规则）
conveyor:
  length_mm: 1200
  speed_mm_s: 200          # 一件料从入口到分拣位 ≈ 6s
  item_spacing_mm: 300
cylinder1:
  stroke_ms: 1800          # 伸出全程（决定 afterMs: 3500 的窗口假设）
  retract_ms: 1200
  sensor_response_ms: 20   # 磁开响应
# 一致性自检：stroke_ms(1800) + sensor(20) + 裕量 < SortTimeOut(2000)
```

### tests/suite.yaml

即 5.4 的三个用例（normal_cycle / estop_mid_cycle / timeout_fault）全文，此处不重复。

### expected/（黄金基线）

| 文件 | 生成方式 |
|---|---|
| `trace_normal_cycle.parquet` | 首次 `plcagent run demo-d1 --kind generate` 全绿后由 Reporter 落盘；此后只读 |
| `report.pdf` | 同上 |

重录流程：改 Spec 或 plant 参数 → 删除 expected/ → 重新 run → 人工确认波形合理 → 提交评审（黄金基线变更走 PR）。

## 21.3 D2 / D3 样例工程定义（CI 端到端依赖，此前仅提名未定义）

| 样例 | 工艺 | 规模 | 覆盖的验证点 |
|---|---|---|---|
| D2 双泵交替 | 两台泵主备切换运行，累计运行时均衡，故障自动投切 | 16 IO / 1 状态机 + 2 sequence | StartStopHold 模板、时间累计（CTU）、设备切换互锁 |
| D3 加药 PID | 液位罐进水 PID 调节 + 加药泵联锁（复用 09 号加药工艺） | 24 IO / 1 状态机 + PID FB | 模拟量输入/输出、PID 标准块、量程换算、断线保持（故障注入） |

D2 随 P0 W4 交付（评审集 B 组依赖其模板），D3 随 P0 W6 交付（C 组 PID 题依赖）。三个样例共同构成 14.2 端到端层的 `plcagent verify --baseline` 矩阵。
