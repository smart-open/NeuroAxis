## 附录 A：D1 样例工程目录

```
demo-d1/
  spec.yaml            # 3.2 全文
  expected/            # 黄金基线
    trace_normal_cycle.parquet
    report.pdf
  tests/suite.yaml     # 5.4 用例
  plant/params.yaml    # 元件参数(行程ms等)
```

跑通命令：

```bash
plcagent new demo-d1 --template conveyor_sorting
plcagent edit demo-d1/spec.yaml          # 或 Studio
plcagent run demo-d1 --kind generate     # 全闭环
plcagent verify demo-d1 --baseline expected/   # CI 回归
```

## 附录 B：术语

| 术语 | 含义 |
|---|---|
| Spec / IR / ST | 人写的工艺规格 / 中间表示 / IEC 61131-3 结构化文本 |
| trace | 一次仿真的逐扫描信号与插桩记录 |
| 闸门 Gate | 人工或自动的通过点（Gate_Spec / Gate_Result） |
| 影子模式 | 只读采集真机 IO 与仿真对拍，不写 |
| A/B/C 档 | 厂商落地三档（7 章） |

## 附录 C：参考

- IEC 61131-3:2013 / IEC 61131-10（PLCopen XML）
- [OpenPLC（GPLv3，仅作 A 档运行时参考）](https://github.com/thiagoralves/OpenPLC)
- [matIEC（LGPL，iec2c 编译器）](https://github.com/beremiz/matiec)
- [Beremiz（开源 IEC IDE 架构参考）](https://industrialmonitordirect.com/blogs/knowledgebase/beremiz-open-source-iec-61131-3-ide-project-status-and-alternatives)
- [NModbus（MIT）](https://www.nuget.org/packages/NModbus)、[S7NetPlus（MIT）](https://github.com/S7NetPlus/s7netplus)
- [TIA Portal Openness（B 档依赖，需本机 TIA）](https://cloud.tencent.com/developer/article/2702029)
- 手册内：[13 平台](13_插件化工业软件平台_技术架构与二次开发方案.md)（复用契约）、[02 通信](02_下位机通信实战.md)（驱动与模拟器）、[09 加药](09_项目设计说明书_污水加药联动系统.md)（PID 闭环样例可做 D3）

## 附录 D：外部契约摘录清单（`docs/contracts/` 待补，P0 并行轨道）

本产品大量引用"13 号平台"的结论但不重写。拆分后原文档不在本仓库，为使实施者可独立开工，P0 期间将以下契约**摘录**（非全文复制，只摘本产品挂接用到的接口定义）到 `docs/contracts/`：

| 待摘文件 | 摘录内容 | 消费方 |
|---|---|---|
| `contracts/13-plugin-manifest.md` | `kind: Copilot` 插件 manifest 格式与加载约定 | Studio 挂接（0.4） |
| `contracts/13-rbac-audit.md` | 9 章 RBAC 权限码表 + 9.7 审计哈希链字段定义 | 双人复核（4.6）、审批链（P1-⑤） |
| `contracts/02-driver-contract.md` | 驱动契约接口（Modbus/S7 驱动如何注册） | F9 真机对接 |
| `contracts/13-write-four-gates.md` | 5.6 写四闸定义 | 真机写入四阶段（10.2） |

每份摘录文件头部必须注明来源文档编号与章节、摘录日期、原文是否可能演进（演进时由谁同步）。拿不到原文时的降级口径见《03_实施计划》第 4 节。
