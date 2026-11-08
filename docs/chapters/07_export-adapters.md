# 7. 导出与厂商适配（A/B/C 三档，别吹）


| 档 | 目标 | 交付物 | 人工动作 |
|---|---|---|---|
| A 全自动 | OpenPLC Runtime / CODESYS Control Win（仿真/软PLC） | ST 源码 + matIEC 编译通过 + 下载脚本 | 一键 |
| B 半自动 | 西门子 S7-1200/1500（TIA Openness）、CODESYS IDE | SCL/ST + PLCopen XML + 变量表 CSV，Openness Worker 自动建块导入（需本机装 TIA） | 确认硬件组态、编译、下载 |
| C 仅交付 | 三菱 FX5U、汇川、欧姆龙 | ST/指令表 + IO 表 + 接线说明，工程师导入 | 全人工导入 |

三档共用同一份 IR，只是导出器不同。**硬件组态、安全组态永远人工**（这是 B 档的边界，不是缺陷）。

许可证红线（A8）：matIEC 以独立子进程调用、独立目录存放（LGPL 边界）；不静态链接 OpenPLC 运行时；S7NetPlus/NModbus 为 MIT 可放心商用。

---
