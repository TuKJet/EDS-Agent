# CAE Agent Hub 实机验证

2026-11-03 最新进展：**小型传热 demo 的建模、三次求解、数值一致性、热平衡和结果图检查通过。**
这是一项有明确边界的小型演示，不等于完整 CAE 物理方案比较、联合工程或全部验收案例通过。
下文蠕变预览文件的加载失败是保留的历史结果，不能作为新 demo 的求解结果。

后续物理方案比较已有一个真实工况：在相同 0.2 W、网格 3 下，加上规定发射率 0.8 的表面对环境
辐射后，最高温度为 317.872353013 K，散热面平均温度为 317.847605931 K；独立积分的对流与辐射
热流分别为 0.147732044481 W 和 0.052268026099 W。相对热平衡误差约 3.53×10⁻⁷，温升相对
仅对流结果降低约 26.1%。主代理核对实际边界、材料与发射率来源，并打开真实温度图。
完整选型仍需 0.4 W 及其网格检查，不能由该单点直接宣称通过。

该轮三次求解尝试中，前两次初始化失败：数值已设为 0.8，但 `epsilon_rad_mat` 仍为 `from_mat`。
将来源明确设为 `userdef` 后第三次收敛。原失败和预算耗用保留；后续两个工况另记为
`radiation-high-load-followup@1`，最多两次尝试，不追改原预算。所有修正均为测试模型设置，
没有修改 CAE MCP 源码。证据见
[低载荷独立复核](../workspaces/live-cae/radiation-low-load-owner-review-20261103.json)。

本次使用用户选定的 CAE Agent Hub，固定提交
`56705e07ce6e99f0d5a0d0c7b5e28b6b2c0bc973`。原 Mems MCP 不参与验证。
用户确认同事使用结束后恢复任务；同事的服务、模型和允许名单没有修改。

## 小型传热 demo：数值与可视化核验

执行者经选定 MCP 建立 `EDS_SMALL_THERMAL_20261103`，20×10×5 mm 铝块，
一个加热边界、五个互不重叠的对流边界；环境温度 298.15 K。共享计算进程使用一个核，
满足最多两核的预算。这里的共享连接指客户端连接同一 COMSOL 后台模型；不表示复用同事模型。

主代理从实际 MCP 回执独立复核了三个非空解和以下数值：

| 工况 | 网格四面体数 | 最高温度 K |
| --- | ---: | ---: |
| 0.2 W，初始网格 | 3731 | 324.841410207 |
| 0.2 W，加密网格 | 12182 | 324.841414591 |
| 0.4 W，同一加密网格 | 12182 | 351.532829182 |

加密前后的最高温升相对变化约 0.0000164%，功率翻倍后的温升比为 2.000000000，
均满足预先记录的 1% 判据。实际回执、文件指纹和复核计算见
[主代理数值复核](../workspaces/live-cae/small-demo-owner-numeric-review-20261103.json)。
这些检查证明该算例的数值一致性，尚不构成完整物理方案比较或预测验证。

首个原生 MPH 已保存并下载。首个 PNG 虽然工具报告导出成功，但主代理打开后看到的只有
白色画布与坐标轴，没有温度场、色标或单位，因此该次可视化检查失败，原图保留。
后续经 MCP 重新读取已保存模型，将 `pgtemp` 及其 `surf` 绘图节点显式绑定至 `dset1`，
导出得到可见温度场。主代理实际打开新图，核对了块体形状、温度分布、色标、摄氏度及
毫米单位。图中自动色标仅标注 78.3°C；精确最高温度为 78.382829182°C，以数值回执为准。

MCP 后处理积分得到对流面积 0.0005000000000000019 m²、对流总热流
0.4000000000012986 W；相对输入 0.4 W 的误差约 3.25×10⁻¹⁰%。通过
`h(∫T dA − Tamb·A)` 独立交叉计算也得到约 0.4 W，满足原 1% 判据。
早期积分尝试的 Java 数组转标量失败已修正为正确读取矩阵；失败回执保留。
实际选区是加热 `[3]`、对流 `[1,2,4,5,6]`；执行者曾将对流编号简写错为“1–5”，
该摘要笔误已更正，没有修改模型选区。

后处理未增加求解，也未改变物理条件。新保存的原生模型与非空图片均已取回并校验哈希：

- [最终后处理核验](../workspaces/live-cae/small-demo-owner-final-review-20261103.json)
- [原生 MPH](../local/cae-small-demo/EDS_SMALL_THERMAL_20261103-postprocessed.mph)
- [实际温度图](../local/cae-small-demo/temperature-bound-20261103.png)
- [执行清单](../local/cae-small-demo/execution-manifest-20261103.json)

Headless 并不限制结果为文字。COMSOL 支持从结果绘图导出图像，并提供软件渲染选项，见
[官方图像导出说明](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_ref_results.37.214.html)。
验收应同时检查原生模型与求解数据、数值量及质量、实际结果图及其数据集对应；
如需证明桌面同步，再单独检查相同模型标识的桌面视图。导出回执不能代替打开图片检查。
本 demo 的后处理修正通过已有 MCP 的脚本入口修改模型绘图设置完成，没有修改 CAE Agent Hub
执行源码。保存文件重开后运行标识为 `model1`，模型名称仍为 `EDS_SMALL_THERMAL_20261103`；
这不表示更换模型。最后自有 2037 后台服务已恢复并留置，桥接未连接，没有活动求解；
以 `local/cae-small-demo/status-2037-left-running-20261103.json` 为该次状态证据。

## 原蠕变预览模型的历史执行结果

| 检查 | 结果 |
| --- | --- |
| VM 内 MCP 握手 | `COMSOL MCP`，协议 `2025-11-25`，40 个工具；返回的 `1.30.0` 是 SDK 版本 |
| 独立 COMSOL 会话 | 6.3，2 核，stand-alone；启动前确认该 Hub 没有活动会话，启动后模型列表为空 |
| 启动任务 | `comsol_start_91c1dc601509`，实际从 queued 转为 connected |
| 算例副本 | 复制到 `C:\Work\eds-cae-hub\experiments\creep-20261103\variable-load-creep.mph`，没有覆盖源文件 |
| 文件指纹 | 22313 字节；源文件前后与副本 SHA-256 均为 `36f8b7039908b16011aab7500dc1542555ea8f72e10a418eea229a0b8d83f37b` |
| 模型加载 | MCP 传输成功，但工具内容 `success:false`；COMSOL 明确返回“这是 COMSOL‘案例库’预览文件” |
| 求解与数值结果 | 未执行；无本地 QoI、收敛或模型优劣结论 |

首次子任务在上传前的管理通道检查失败，主代理确认脚本和目标文件不存在、Hub 会话未启动，
将该 Run 记为失败后才建立新意图。主代理随后逐步调用真实 MCP，保存了启动任务编号、状态和
原始响应。第二个 Run 因预览文件不可加载而失败，没有把 HTTP 成功当作模型操作成功。

## 外部连接检查

用户明确授权只排除新程序 TCP 8001 的阻断且不备份后，执行前读回发现：指定规则在
PersistentStore 与 ActiveStore 中均已变为 `Allow`。脚本的身份检查因此在修改前拒绝执行，
没有改写规则。随后经本机 `28502 → 宿主18002 → VM2:8001` 完成实际 MCP 握手，返回
`COMSOL MCP` 和 40 个工具，原先的连接缺口在这次协议验证中消除。
证据为 [外部握手](../workspaces/cae-hub-deployment/external-discovery-authorized-20261103.json) 与
[规则现场回读](../workspaces/cae-hub-deployment/resume-rule-refresh-20261103.json)。

此前排查记录如下：

正确的新路线是宿主回环 `18002 → VM2:8001`，旧 `18001 → VM2:8000` 保持原用途。
经 SSH 使用正确路线仍超时。宿主发布、DNAT/SNAT 与发送放行计数已核对，未收到回复；
Windows 同时存在精确 8001 放行规则与新 Python 的 Public 配置 TCP 全端口阻断规则。
显式阻断会优先于冲突的放行规则，参见
[Microsoft 的防火墙规则说明](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules)。

已准备“先备份、只从该程序 TCP 阻断范围排除 8001”的修复脚本，但自动审批拒绝了持久
安全设置修改，已请求用户明确授权。防火墙尚未改变，修复效果也尚未验证。
本轮 COMSOL 操作通过已认证的 WinRM 管理通道，在 VM 内以官方 SDK 调用同一个 Hub；
这不等于外部 MCP 路线已通过。

## 原蠕变算例的历史结果与证据

完整官方算例原为后续条件；用户随后明确改用小型 MCP demo，因此不再等待或重试该预览文件。
若未来恢复蠕变复现，仍须取得完整资产、记录新版本和指纹，回读物理设置与单位后才能求解。
当前参考目标只是官方表达式的算术值，不是本地 COMSOL 输出。

- [VM 内握手](../workspaces/cae-hub-deployment/resume-guest-health-20261103.json)
- [启动响应](../workspaces/cae-hub-deployment/resume-start-01-20261103.json)
- [启动状态](../workspaces/cae-hub-deployment/resume-start-query-01-20261103.json)
- [加载响应](../workspaces/cae-hub-deployment/resume-open-01-20261103.json)
- [原始 UTF-8 加载结果](../local/cae-hub-root-actions/open-01.result.json)
- [副本清单](../local/cae-hub-root-actions/copy-manifest.json)
- [Study](../workspaces/live-cae/study/study.json)
- [独立参考复核](../workspaces/live-cae/preflight-reference-20261103.md)

Study 中 `hub-reference-preview-rejection@1` 保留实际失败，
`hub-reference-availability-assessment@1` 保存其对下一步的影响；AC-05 仍未通过。

最终回读确认：独立会话仍连接、2 核、模型及跟踪模型列表均为空；没有未决求解。
MCP 专用任务已移除多余定时触发，仅手动启动，现有监听进程未重启。
本机临时 SSH 转发已清理。续作状态见
[接续记录](../workspaces/live-cae/hub-resume-state-20261103.json)。
本轮本地回归再次 **104/104 通过**（26.271 秒），编译检查通过；这不替代未完成的实机求解。

## 本地绑定与响应记录复核

根据本轮保存的 40 项实际工具 schema，建立了仅保存在 `local/` 的 Hub 绑定。
源码版本、工作树、所需工具和绑定检查通过，状态为
`ready_for_mcp_docs_and_binding_review`；这仍然不是宿主 MCP 路线或工程验收通过。
绑定中的 `inspect` 只表示模型摘要，`configure` 只表示已有参数赋值，不能据此宣称任意
物理建模能力。启动限制为最多两核独立会话，保存必须显式提供目标路径。

离线验证覆盖 10 种调用参数结构及 3 种应拒绝的输入，并使用已保存的真实响应回放：
异步启动回执记为 `submitted` 且保留任务编号，预览模型加载记为 `failed`，会话查询记为
该次查询 `completed`。回放没有连接 VM；查询完成不代表求解完成。

- [绑定检查](../workspaces/cae-hub-binding-validation/readiness.json)
- [参数结构检查](../workspaces/cae-hub-binding-validation/call-shapes.json)
- [真实响应的离线回放](../workspaces/cae-hub-binding-validation/recorded-response-replay.json)

这些离线检查只改善调用准备和执行记录；外部连接以本次实际握手为准，真实求解另行验收。

本地单次调用助手后续复核与回归已达到 **112/112 通过**（28.513 秒），编译检查通过。
外部连接的最新协议结果见上文；小型 demo 使用已记录的 `small-thermal-demo@1` 与
`small-thermal-demo-check@1`，复用上游两阶段铝块传热示例，分别检查几何/边界、热平衡、
网格加密和功率翻倍响应。实际求解及未通过检查见本文顶部，参数结构检查仍不算真实求解。
# 2026-11-04 独立物理方案比较结果

对流与对流加辐射的限定比较已完成，保存模型的持久化核对也已通过。0.2 W 和 0.4 W 下，
加入规定的发射率 0.8 后，最高温升分别降低约 26.1% 和 27.9%，超过预设 10% 判别阈值；
高载工况的网格温升相对变化为 3.18e-9。结论是在本次规定条件下保留对流加辐射模型。

零求解重新打开两份 MPH 后，实际网格分别为 12182 和 47935 四面体；保留解的最高温度为
317.87235301278105 K 和 336.6219188335724 K。依据实际读回的对流、辐射积分计算，
相对热平衡误差分别为 3.53e-7 和 7.71e-7，远端/本地文件 SHA-256 一致。
已审阅的温度图证据保留，未以文字或导出成功替代图像检查。

主代理独立复核位于 `workspaces/live-cae/radiation-persistence-owner-review-20261104.json`，
结论记入 Study 的 `radiation-physics-assessment@1`。高载跟进原预算两次而实际求解三次、
两个前置只读探测未登记 Run、QA 重建同名后处理节点等偏差均保留。最后一次核对没有新求解、
修改物理条件或保存模型。该结果不代表材料校准、制造放行或联合验收已完成。

