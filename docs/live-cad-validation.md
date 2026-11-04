# CAD 实机验证与执行 Skill 接入

2026-11-02 首轮记录：**基础 CAD 几何链与接入检查通过，完整 CAD 研究验收尚未通过。** 后续切除修复已完成针对性实机复验，见[修复复验报告](live-cad-repair-validation.md)；本页保留首轮失败与条件，不改写历史结果。

## 来源

Codex 直接加载 EDS 方法和 `execution-skills/solidworks-automation-skill/SKILL.md`。执行实现采用独立 submodule，分支 `vm-sw-automation-skill`，锁定 `8a572ce6fa4d78e6ee75f03cc14547cf94830d8a`，工作树无修改。VM1 抽查的七个文件规范 BOM/换行后与该提交一致；不能据此证明整个 VM 目录版本。

实际服务 `solidworks_mcp` 初始化报告版本 `1.30.0`，SolidWorks revision 为 `33.0.0`，发现 66 个工具。服务版本字段不替代源码提交证据。连接复用已有认证、SSH 转发及官方 Python MCP SDK；未复制 SolidWorks 实现，未修改 VM 服务。

## 真实检查

证据编号对应 `workspaces/live-cad/evidence/` 文件。

| 检查 | 结果 |
| --- | --- |
| 服务与应用健康 | 正常；最初无活动文档，COM 依赖齐全。`01`、`02` |
| 基体与参数修改 | 从 100×20×10 mm 开始。实际尺寸 `D1@草图1` 为半宽：50→120 导致总宽100→240；确认映射后设为60，得到120×20×10 mm。`03`、`09`～`15` |
| 独立几何参考 | `V=120×20×10=24000 mm³`，`S=2(120×20+120×10+20×10)=7600 mm²`；实测一致。预定尺寸容差0.01 mm、体积/面积相对容差0.001。 |
| 草图与重建 | 单实体、6面；草图完全约束、2个驱动尺寸、14个关系、0 Fix、无悬空草图；重建与特征错误检查通过。`19` |
| 保存重开 | 关闭后从磁盘重开原生文件，体积仍24000 mm³、面积7600 mm²。`36`～`38` |
| STEP 几何回导 | 下载15820字节，SHA-256 `71a87ccec5d1790fad528600fd45f23f630eb3002163f0e06f2108a67f41dcc9` 匹配；回导新零件后实体数、边界、体积、面积一致。`20`～`25`、`31` |
| 实际预览 | 已查看取回的等轴测PNG，完整矩形长条，无通孔，与基础测试范围一致。`22` |
| 原生交付 | 两个SLDPRT取回并对照远端哈希；首次被文件占用阻断，关闭本轮文档后成功。`35` |
| Skill 加载 | 独立接管代理按仓库指引加载 EDS、submodule Skill、能力清单和建模参考；识别CAE待选，未混用CAD绑定。该独立检查只读，不调用VM。 |
| 实际调用门禁 | 错误服务名、负尺寸参数均 `preflight_rejected=true`、`tool_sent=false`；正确配置随后回读真实模型并记录schema哈希。`29`～`31` |

共保留35次MCP会话：1次能力发现、32次实际工具调用、2次调用前拒绝。上游 `sw_preflight.py --no-install` 在VM完成，未安装依赖。只操作本轮隔离目录，结束时关闭本轮原生文档。

## 未通过与限制

- 矩形切除真实失败，MCP没有切除方向参数。两候选开孔和厚度10→12 mm负例未完成，原计划CAD闭环未通过。
- 源码存在 `cut+midplane` 分派/报告不一致、`feature_name` 未应用；未执行该危险组合。见 [上游诊断](solidworks-mcp-findings.md)。
- 另存为后第一次审查因旧文档绑定被拒绝；显式打开新路径重绑定后成功。
- 回导件返回12条边，但边长全为null，错误列表含读取失败。边长度测量未通过，不能用 `status:ok` 掩盖。
- 原件未指定材料；回导质量接口报告 `Steel`、密度却仍为1000 kg/m³，特征树仍显示未指定材料。只接受几何回导结论，不接受质量或材料保持结论。
- 上游审查仍为 `review_required`，MCP没有 `expected_outputs` 入参；本轮用独立文件、哈希、数值和目视检查补充交付证据，不作制造放行或力学结论。
- 初期Run的 `completed` 仅表示收到回复，切除失败另存Evidence/Assessment；接入程序随后补充payload失败判定，后续明确失败为 `failed`。Run终态始终不代替工程评估。

缺陷应回对应执行仓库维护。更新submodule固定版本与VM后须重新发现schema、复验。本工程未保留独立SolidWorks实现或补丁。装配、出图、运动、CAE、联合任务及全部原始AC未因此通过。费用和人工交互总数未可靠采集，保持缺失。

## 本地产物

- [验收摘要](../workspaces/live-cad/validation-summary.json)、[证据哈希清单](../workspaces/live-cad/evidence-manifest.json)、[Study报告](../workspaces/live-cad/study-report.json)
- [原生零件](../workspaces/live-cad/artifacts/basic-120x20x10.SLDPRT)、[STEP](../workspaces/live-cad/artifacts/basic-120x20x10.step)、[回导零件](../workspaces/live-cad/artifacts/basic-roundtrip.SLDPRT)、[预览](../workspaces/live-cad/artifacts/basic-final-preview.png)

本地工作区被Git忽略，新checkout不自带这些工程文件或连接信息。
