# CAD 切除修复实机复验

2026-11-04 当前结论：A10/A12 均取得完整的 24 条直线边，闭合环回读确认外形 100×20 mm、
开口 60×8 mm、端部余量 20 mm、侧部余量 6 mm，厚度分别为 10/12 mm。
B 取得完整九面回读；三个直径 14 mm 的孔、完整外表面、体积及贯穿高度共同支持贯通孔几何。
本轮几何目标下选择 A，仍不作强度、材料质量或制造放行结论。具体证据见
[最终候选比较](../workspaces/live-cad/final-candidate-assessment-20261104.json)。
用户另行要求跳过人工修改验收，已准备的独立副本保留，不将其准备过程计作人工修改测试通过。

以下保留 2026-11-03 的修复与当时证据边界。

2026-11-03 后续实验更新：F74 最终版本部署后，普通 STEP 打开被拒绝且活动文档保持一致。
A 矩形通窗与 B 三圆孔的实际体积分别为 15200 mm³ 与 15381.858799223 mm³。
最新独立调用还确认厚度 12 mm、切深 10 mm 的负对照已具有 `AResumeT12Blind10`、
19200 mm³、11面；此前“负对照未形成”的摘要不准确。失败的后续尝试仍保留为各次真实失败，
不能据其推断已有特征不存在。见
[当前负对照状态核对](../workspaces/live-cad/negative-readback-reconciliation-20261103.json)。

厚度 12 mm、切深 15 mm 的修正候选实际体积为 18240 mm³。A 的 10 mm 和 12 mm 版本
已另存、重开和回读，并生成 STEP 与预览；主代理也打开了两张等轴图。几何核验与制造审查
分开：仍保留 `review_required` 和草图驱动尺寸缺口，不把预览或体积匹配当作制造放行。
B 的内存结果曾在切换文档后无法从其基础文件恢复，但一次误标为 A 的已保存文件保留了 B
三孔几何；已实际回读并另存 `B-resume-final-recovered.SLDPRT`，后续重开、STEP 和预览已通过。

最新 A 专用 STEP 回导已保存为 `A-resume-final-step-roundtrip.SLDPRT`，回读为单实体、
100×20×10 mm、15200.000000000002 mm³、10 面，文件下载哈希匹配。此前的活动文档错误是
调用者将输出路径误填为 `expected_document_path`；该参数应保护调用前的活动原生文件，
修正参数后通过，无需新增上游补丁。导入结果为 `BaseBody`，不声称保留原参数化特征树。
A/B 实测表面积分别为 6800.0 和 6795.840674 mm²，符合原公式；孔尺寸和边距仍待原生测量。
见 [最终工件独立复核](../workspaces/live-cad/final-artifacts-owner-review-phase2-20261103.json)。

保存过程中曾在打开 B 后未真正重新激活 A，就保存到 A 文件名；回读识别到 B 的实际特征
和体积，错误命名文件保留，正确 A 另存新文件，没有覆盖基础模型。独立诊断确认单次调用
助手会拒绝重复的终态意图，不会静默返回缓存成功来激活文档；不能忽略该拒绝后继续保存。
部分早期重试绕过 Study 的历史也明确保留为事后证据，不补造事前意图。

2026-11-03 续作：用户确认无路径的 `A-cut.SLDPRT` 是测试临时文档并允许丢弃后，
上游增加了显式名称/类型/丢弃确认的关闭入口。原始回执及后续连接确认该临时文档已关闭。
专用 STEP 回导保存为 `A-cut-step-roundtrip.SLDPRT`，实际为单实体、100×20×10 mm、
体积 15200.000000000002 mm³、10面、警告0；仍保留 `manual_review_required=true`。

最初关闭补丁曾在独立复核前提前部署；随后暂停进一步修改并补齐审查。最终源码补上同名
文档（含不同类型）的歧义拒绝、关闭后确认，以及普通打开在 COM 调用前拒绝非原生格式。
最终本地提交 `e394e18d250f31f60a8f5b4c41a541d80b31fd8b`，server.py SHA-256
`f74f78f5fc88067f6d74dae27da721d02a8a2b1672b7509116ce5adc129bf549`，针对性测试
17/17通过（2.51秒），独立源码复核无剩余阻塞。随后才释放最终版本的部署及后续实验任务。

证据：`workspaces/live-cad-repair/evidence/close-unsaved-explicit-20261103.json`、
`connect-after-explicit-close-20261103.json`、`import-step-roundtrip-20261103.json`；测试日志
`workspaces/validation/cad-unsaved-close-20261103/mcp-native-close-final.log` 与同目录 JUnit XML。
此处不把此前补丁上的回导结果自动计作最终版本全部实机实验通过；A/B 与厚度实验的后续状态见本文顶部。

以下保留早期切除修复与身份问题的定位记录。

2026-11-02。**显式方向切除、特征命名、非法组合拒绝和原生重开通过；STEP 回导的文档身份
尚未确认，完整 CAD 研究闭环仍未完成。**

修复位于独立 SolidWorks submodule 的本地提交
`a5aa273fabe17167af5c370965a3924c3e1de28c`，未推送。部署前确认 VM1 无活动文档、MCP
无活动连接；备份旧 `server.py` 后仅更新该文件和重启对应 MCP，未重启 SolidWorks。
部署后文件 SHA-256 与本地固定提交的生产文件一致：
`3a680befc8d3ae90a06fd992ede72eaba1ffc929b4a210a5e0f57f7aa2636922`。

## 真实结果

预定尺寸误差不超过 0.01 mm，体积相对误差不超过 0.001；未根据实跑结果调整阈值。

| 检查 | 结果 |
| --- | --- |
| 100×20×10 mm 基础体 | V=20000 mm³，边界尺寸一致 |
| 中央 60×8 mm、深 10 mm 切除 | 显式 `direction=false`，V=15200 mm³，单实体、10 面 |
| 特征名称 | `CentralCut60x8` 在返回及独立特征树回读中一致 |
| `cut+midplane` | 返回错误；拒绝前后实体、面数、体积和特征树一致 |
| 原生保存并重开 | V=15200 mm³，表面积6800 mm² |
| 目视 | 主代理查看正视/等轴预览；正视中央矩形开口可见背景，与通窗表达相符 |
| STEP 导出 | 输出25088字节，SHA-256 `f701f4625d52c6a1962a251c6f921f6d2b692307a2aad8ff38c87288ca38af2a` |
| STEP 新文档回读 | 未通过文档身份核对；不能把相同体积当作回导成功 |

主代理独立断言了几何数值、非法请求前后状态和部署文件哈希；不是仅采用执行代理的成功摘要。
本轮上游相关离线测试18项通过，EDS路由/CLI测试6+8项通过；Skill安装副本一致。

## 剩余状态与限制

普通 STEP 打开返回无法核实路径/类型；随后活动文档为同名 `A-cut.SLDPRT`，路径为空。
这可能与打开过程中的隐式导入有关，尚不能判定为旧原生文档残留。重新打开原生文件遇到
同名已开文档；guarded STEP import 要求路径一致，因此拒绝。没有强制关闭未知身份文档，
下一步先用可证实的本轮文档身份完成安全恢复，再验证专用导入路径。

审查仍为 `review_required`，切除草图无驱动尺寸；材料未指定，默认密度算出的质量不作为
工程结论。此轮只验证修复对应几何操作，尚未完成旧 Study 的 A/B 比较、厚度变更或 CAE。

## 证据

- [主代理独立核对](../workspaces/live-cad-repair/independent-check.json)
- [Study及原始运行记录](../workspaces/live-cad-repair/study.json)
- [Study报告](../workspaces/live-cad-repair/study-report.json)
- [原生零件](../workspaces/live-cad-repair/artifacts/A-cut.SLDPRT)及 [STEP](../workspaces/live-cad-repair/artifacts/A-cut.step)，均已取回并对照远端哈希；取回不等于 STEP 回导通过
- [文件清单](../workspaces/live-cad-repair/artifacts/manifest.json)
- [正视预览](../workspaces/live-cad-repair/evidence/previews/A-cut_front.bmp)
- [等轴预览](../workspaces/live-cad-repair/evidence/previews/A-cut_isometric.bmp)

旧生产文件备份：`local/cad-repair/remote-server.py`；部署前后证据位于同一忽略目录。

## 文档身份问题定位

低层打开 STEP 会用 `LoadFile4` 生成无路径的新导入文档；普通 MCP `open_document` 却要求
返回非空路径，故可能在文档已经创建后报错。这是接口契约不一致，不能把后续相同体积认作
回导链成立。现有关闭/重绑定接口也不接纳这个无路径文档。当前未绕过门禁；已请求在 VM1
窗口确认关闭本轮测试件。

预防同类问题的上游修复已另存为本地分支 `codex/fix-native-open-boundary`、提交
`8760cf2dc721aef342d9991b80f36844f3a30df1`：普通打开只接受原生格式，STEP 在 COM 调用前
被拒绝并指向专用导入；当前已保存 guard 和新的原生输出路径分别指定。其19项相关测试
通过，尚未部署或推送。工程 submodule 仍保持已部署的 `a5aa273`，避免把准备中的修复
当成远端已生效版本。当前文档身份问题解决后，再更新版本并实测专用导入链。
