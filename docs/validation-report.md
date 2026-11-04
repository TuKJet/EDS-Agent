# 本地实现与验证报告

更新至 2026-11-04。第一宿主：Codex。本报告先记录 MCP 接入前的开发与离线验证，再补充实际接入状态。

当前交付汇总见[交付状态](delivery-status.md)：16 项通过、AC-07 待真实新会话验证、AC-10 用户跳过。三个 Study 均无未决 Run；整体目标和 M4 尚未标记完成。

当前范围：本地补丁自动安装已完成；CAD 独立几何候选比较与 CAE 独立物理候选比较已完成代表性实机验收。
联合任务已完成实际 CAD→CAE 对应、温度反馈驱动的厚度修订和只改载荷的单端复用。10 mm / 5 W 基线最高约 63.64℃；14 mm / 5 W 为 58.13℃；保持几何和网格、仅改为 4 W 后为 51.68℃。两网格质量、热平衡、原生文件哈希和实际云图检查均已完成。T14 连接失败及 4 W 后处理命名冲突的原记录保留，恢复过程没有重复求解。见[联合验收记录](live-coupled-validation.md)及[联合交付](../workspaces/live-coupled/final-delivery-report-20261104.md)。
用户已明确跳过 AC-10 人工修改验收，状态为 `skipped_by_user`，不计作通过；跨会话接续仍待实际验证。
最新需求证据归档为 `workspaces/validation/requirement-evidence-archive-20261104.json`，
逐项状态以 `workspaces/validation/acceptance-ledger-20261102.json` 为准。

下文保留开发与接入期间的历史记录；早期“尚未接入”或某项“未通过”的叙述仅表示当时状态，不覆盖当前验收台账。物理假设比较也不等于 B0–B3 方法对照，当前不提出学术增益或跨后端通用性主张。

当前已追加第五份文档状态与关闭保护补丁，原四份补丁未改写。最新本地回归 **140/140 通过**（156.710 秒），编译检查通过，日志为 `workspaces/validation/execution-five-patch-tests-20261104.txt`；六组相关执行端回归 **69/69 通过**（13.89 秒），日志为 `local/cad-document-guard-patch5-20261104/vendor-tests-complete-runtime.txt`。
在独立公开基础提交 checkout 上首次安装、从完整四补丁前缀升级、重复安装和只读检查均通过，11 个目标文件与源码一致，证据为 `workspaces/validation/execution-five-patch-install-20261104.json`。工作区安装只读检查也为 `in_sync`。第五份补丁随后已部署到 VM1 的所选 MCP，仅替换 `server.py` 并重载 MCP，SolidWorks PID 4164 保持不变；真实文档状态检查发现 10 个打开文档，其中 4 个有未保存修改。部署与只读调用分别记录于 `local/cad-document-guard-patch5-20261104/deployment/deployment-20261104.json` 和 `workspaces/live-coupled/cad-capacity-check-20261104/inspect-documents-result.json`，未据此自动关闭或保存文档。

此前四补丁版本地回归为 **140/140 通过**（72.029 秒），编译检查通过，日志为
`workspaces/validation/execution-patches-four-tests-20261104.txt`；新增检查证明从完整三补丁前缀升级到四补丁时仍保留冲突保护。
公开新克隆的升级验证覆盖 11 个目标文件与重复安装不改写，证据为
`workspaces/validation/execution-four-patch-upgrade-20261104.json`；六组执行端回归 **62/62 通过**（6.57 秒）。
随后真实 SolidWorks 接口编译发现 `GetSurface()` 返回值缺少显式转换；已修正并保留失败记录。
最终四补丁版在新的公开基础提交 checkout 上首次安装、重复安装和只读检查均通过，11 个文件与本地源一致；
证据为 `workspaces/validation/execution-final-patch-install-20261104.json`。
该最终副本六组执行端回归 **62/62 通过**（15.39 秒），日志为
`local/patch-install-final-cast-20261104/vendor-regressions-final.txt`。
修正后的 C# 已使用 VM 实际 SolidWorks PIA 编译通过，见
`workspaces/live-cad/geometry-observables-compile-20261104.json`。
后续实际六平面基础件与 B 九面三孔件回读均通过，见
`workspaces/live-coupled/baseline-cad-owner-review-20261104.json` 与
`workspaces/live-cad/final-candidate-assessment-20261104.json`。
该四补丁阶段及 11 个目标文件的内容复核为 `workspaces/validation/execution-patch-current-review-20261104.json`。

此前本地回归为 **139/139 通过**（57.461 秒），编译检查通过，日志为
`workspaces/validation/execution-patches-tests-20261103.txt`。新增覆盖有序补丁校验、首次安装、
重复安装、CRLF、冲突保留与失败恢复，以及 MCP 预算和未知动作防重。
该历史阶段 CAD 改为公开基础提交 `8a572ce6fa4d78e6ee75f03cc14547cf94830d8a` 加本仓库三份补丁；当前为上述五份。
从公开上游新克隆后，安装器重现的六个文件与已验证源文件完全一致，重复安装不改写文件，
只读安装检查通过；证据为 `workspaces/validation/execution-patch-install-20261103.json`。
当前工作区安装检查和 CAD readiness 也通过，受控补丁差异被识别为 `controlled_patch_changes`。
新克隆副本按上游 MCP 1.x/Windows COM 依赖运行四组修复回归，**51/51 通过**（15.16 秒）；
日志为 `local/patch-install-validation-20261103/vendor-regressions-v1.txt`。
此前隔离测试错误选择 MCP 2.x 导致收集失败，失败日志保留；没有为此改变项目依赖约束。
这些结果证明本地安装可复现，远端边长修复复验另行进行。

此前本地回归为 **118/118 通过**（91.574 秒），MCP 调用助手的针对性测试 **21/21 通过**，
编译检查和独立复核通过。证据为 `workspaces/validation/mcp-markdown-failure-20261103.json`
及同名文本日志。新增检查覆盖文本格式的明确失败状态，修复上游回复 `# error` 却记为完成的问题；
原始回复不改写，历史误分类另加纠正记录。此前超时/终态防重修复的 116 项测试证据保留于
`mcp-terminal-intent-20261103-v2.json`：未收到调用回复时保留 `unknown`，已有终态明确拒绝重发。
这些修改属于 EDS 调用记录助手，没有修改 CAE MCP 源码。

CAE 基础链路和限定工况的物理方案比较已通过真实数值、图像与保存模型回读检查。已记录并独立审查
`radiation-discrimination@2`，比较仅对流与对流加辐射，限定三次求解尝试。前两次因发射率仍从材料
读取而在初始化失败；明确设置为自定义 0.8 后，0.2 W 工况成功，热平衡通过，温升降低约 26.1%。
原预算保留为三次尝试，剩余 0.4 W 两个网格使用新记录的 `radiation-high-load-followup@1`，
限定两次求解尝试，实际执行却重复提交了 mesh2，总计三次，属于流程偏差，历史记录保留。
两档负载的数值与图像已取得，0.4 W 的辐射模型温升降低约 27.9%，网格温升变化约 3.18e-9；
2026-11-04 已完成已保存模型的零求解回读，功率、网格、物理条件、保留解与热量一致，远端/本地原生文件哈希匹配；独立复核见 `workspaces/live-cae/radiation-persistence-owner-review-20261104.json`。
QA 脚本重建了同名后处理节点，不能宣称内存中的结果配置完全未变；没有保存、改物理条件或重新求解。两个前置只读探测未事前登记 Run，原始回复保留，未倒补为事前记录。
AC-16 当前热学知识 fixture v3 已补足同一 0.2 W 原生模型的功率、网格、自由度和结果绑定，三单元六组中英文查询及关系回读经独立复核通过，见 `workspaces/thermal-knowledge-validation/validation-report.json`。范围限内容、来源与召回；关联运行反馈不表示论文复现或材料校准，生产抽取偏好仍为 `later`，历史 v2 缺口记录保留。
CAD 的 A、B 和 12 mm 原生文件已下载并核对远端哈希；B 重开/导出和
当前 A STEP 回导已完成，主代理核对几何与文件。A10/A12 的完整直线边环确认了外形、开口和边距，
B 的完整逐面读回结合孔轴/直径/体积确认贯通孔几何。最终几何比较选择 A；不外推强度或制造放行，
也不追认早期预算已满足。见 `workspaces/live-cad/final-candidate-assessment-20261104.json`。完整需求仍未完成，见
`workspaces/validation/acceptance-ledger-20261102.json`。

以下为迁移到补丁方案之前的历史证据：CAD submodule 更新到本地提交 `e394e18d250f31f60a8f5b4c41a541d80b31fd8b` 后，
首次回归发现测试中仍模拟旧固定版本；已同步该测试数据。随后全量 **112/112 通过**
（42.856 秒），编译检查通过，Skill 副本 `in_sync=true`，使用实际工具清单的 CAD
准备检查为 `ready=true`、版本匹配且工作树干净。实际输出保存在
`workspaces/validation/cad-pin-tests-recovered-20261103.txt`、
`cad-pin-install-check-20261103.json` 与 `cad-pin-readiness-recovered-20261103.json`；
旧失败记录保留。该开发提交未推送；现已由公开基础提交和本地补丁取代其安装依赖。离线准备通过不表示远端安装或实机动作通过。

后续真实桥接启动回复使用 `ok:false,status:not_configured`，暴露了另一种显式业务失败格式。
现已补齐该判断；普通 `running:false` 或 `connected:false` 状态不会因此判为操作失败。
修复后全量仍为 **112/112 通过**（40.608 秒），编译与独立复核通过；实际回复离线核对及日志见
`workspaces/validation/mcp-explicit-ok-failure-20261103.json`。这次桥接启动实际没有创建进程，
须配置上游共享桥接后继续，不能把传输成功记作建模完成。

此前异步记录修复回归 **112/112 通过**（28.513 秒），编译检查通过；证据为
`workspaces/validation/async-mcp-recording-20261103.txt`。MCP 单次调用助手修复异步提交误记完成、
换证据路径重提，以及旧版绑定记录的防重缺口；保留失败任务编号，区分传输不确定与收到响应后
的证据写入失败。15 项针对性测试包括真实调用入口的模拟 SDK 验证：5 类预检失败不发出操作，
正常对照仅调用一次。独立复核未发现剩余代码问题；环境没有 LSP 诊断工具，未将其计为通过。

用户已确认 CAD 临时文档可关闭不保存，并将 CAE 验证改为通过 MCP 从零建立小型 demo。
外部 Hub 握手现已通过，实际返回 40 个工具；原防火墙规则现场已为 Allow，检查脚本在修改前
拒绝执行，未修改规则。热传导 demo 已完成三次真实求解，主代理复核了非空解、网格加密、
功率翻倍响应与热平衡。首张图像为空白；显式指定模型绘图的数据集后，新温度图已实际打开
检查通过，原失败图片保留，后处理没有新增求解或修改 CAE MCP 源码。该 demo 与此前失败的
蠕变预览文件分开记录，最新结果见 [CAE 实机验证](live-cae-validation.md)。

2026-11-03：已按用户选择加入 CAE Agent Hub submodule，并将通用 MCP 实现/文档入口与
专用 Skill 分开登记。本地只读 readiness 覆盖源码、submodule、固定版本、工作树与绑定检查，
不表示实机已连通。独立代码复核通过，全量 **104/104 通过**（27.624 秒），编译检查通过，
证据为 `workspaces/validation/cae-integration-tests-20261103.txt`。VM2 安装后曾按用户要求停止；
用户随后确认同事使用结束并恢复验证。新 Hub 的 VM 内握手通过，外部连接因 Windows
应用阻断规则冲突当时未通过；后续授权及现场变化以本页最新结果为准。模型准备曾使用既有管理通道继续，
实际部署及验证状态见 [CAE 接入盘点](cae-execution-selection.md)。

续作已通过同一 Hub 的 VM 内入口启动独立 COMSOL 6.3 两核会话；官方安装目录中的算例
实为预览文件，复制指纹一致但模型加载被 COMSOL 拒绝，因此没有求解或数值验收。
见 [CAE 实机验证](live-cae-validation.md)。

本轮还根据保存的 Hub 实际 schema 完成本地绑定核对，10 种调用参数结构通过、3 种非法输入
被拒绝；3 份真实响应的离线回放分别保留异步提交、模型加载失败和查询完成的区别。
这些检查没有新增 VM 调用，也不代表配置、求解、取值、导出或保存已在实机执行。
证据位于 `workspaces/cae-hub-binding-validation/`。

2026-11-02 的实机证据：CAD 基础链和后续显式切除修复均有实机证据；后续 STEP 回导遇到文档身份缺口，完整 CAD 闭环仍未通过。原 CAE VM2 Mems 服务已完成认证握手、10项工具发现、状态/模型库只读盘点，并在保留历史 unknown 调用的前提下完成一次成功的只读模型 metadata 回读；本工程仍未发起 solve、build 或 export，也未完成物理方案比较和工程验收。Hub 与原 Mems MCP 不是可直接互换的实现，这些历史调用不算新 Hub 验证。详见 [CAD 首轮报告](live-cad-validation.md)、[切除修复复验](live-cad-repair-validation.md)和 [CAE 接入盘点](cae-execution-selection.md)。

## 交付内容

- 四个原生 Skills：Study、CAD、CAE、联合方法。研究决策、工具调用和抽取由 Codex 直接承担。
- 工程记录：版本固定、原始证据与评估分离、任务状态历史、幂等记录、已知任务接管、跨会话接续、传递变更影响。
- 工程资产：显式文件指纹及人工修改/移除检测。
- 可选知识库：Markdown 完整单元、多处来源、精确版本关系、SQLite FTS/中英文 n-gram、增量更新与原子重建。
- 本地绑定：实际工具能力清单、显式参数/单位映射、未知状态保留；不包含自制 MCP 通信和模型调用。
- 安装器、JSON 命令行、三条离线演示及真实验收任务草案。

实现不修改宿主源码，没有第三方 Python 运行依赖。生产资料与 Skills 分离。

## 环境与证据

- Windows，MSI PowerShell 7；Python 3.14.4；SQLite 3.50.4，FTS5 可用。
- 早期本机 Codex CLI 返回版本 `0.164.0`；2026-11-03 核验当前桌面自带运行程序为
  `0.166.0-alpha.5.1`，OpenAI Authenticode 签名有效，证据为
  `workspaces/validation/host-identity-20261103.json`。未修改宿主源码；不将 alpha 版本记作稳定渠道。
  2026-11-04 当前进程核验为 `0.166.0-alpha.6`，OpenAI 签名有效，见
  `workspaces/validation/host-runtime-current-20261104.json`。保留旧版本快照，不将跨版本记录表述为受控同版本实验。
  实际开发和方法执行使用 Codex 原生会话/子代理。
- 四个 Skills 已复制到本仓库 `.agents/skills/`；`install-skills --check` 显示源与安装副本一致。
- 新启动的独立审查会话收到宿主 Skills 更新，列出四个 EDS Skills，确认原生发现。
- 原生技能格式检查使用 `python -X utf8 .../skill-creator/scripts/quick_validate.py`，四个均通过。
- Python 编译检查、Git diff 空白检查与新增 Python 文件尾随空白检查通过。

Python 3.11+ 是代码兼容目标，本次只实测 Windows/Python 3.14；POSIX 路径和其他 Python 版本未作平台验收。

## 自动测试

逐级披露及接续摘要补充后，全量 **97/97 通过**（28.849 秒），见
[最新全量日志](../workspaces/progressive-disclosure/test-results-20261102.txt)。新增验证原始执行
payload/history 不进入默认摘要，未知任务、失败任务和固定输入版本可定位，按 Run/对象读取
保留完整数据且不修改原记录。编译检查、四个 Skill 格式校验和安装副本同步检查通过。
具体行为与已有 Study 的只读投影检查见[方法前向检查](skill-forward-check.md)。

CAD 接入与submodule安装/路由阶段，全量 **93/93 通过**（72.839秒），见 [该阶段全量日志](../workspaces/validation/test-results-cad-final.txt)。独立复核后又补充非法/空工具schema的调用前拒绝，相关7项MCP客户端测试及编译检查通过；四个Skill格式检查和安装副本同步检查均通过。

第一阶段完整测试 **76/76 通过**（19.939 秒）：工程内核 28、知识库 34、绑定 8、CLI/安装 4、资产 1、三路径集成 1。
执行命令：`python -X utf8 -m unittest discover -s tests -v`。
完整日志保存在 [本地测试日志](../workspaces/validation/test-results.txt)。测试覆盖：

- 多线程/多进程写入、异常进程锁释放、原子替换失败、损坏 JSON、引用种类与固定版本。
- 相同任务键冲突、任务历史、重复状态查询、已有任务先查询、未知任务不重提、终态不倒退。
- 一次/自动/稍后/跳过经验抽取、补抽取、未知费用与上下文变更事件。
- 中文词序变化、混合中英文查询、多字段/来源定位、完整公式条件与循环关系回读。
- 文件新增/修改/删除、重复登记、登记失败、索引损坏、版本断链、增量与重建。
- CLI 独立进程接续、错误退出、中文路径、安装副本冲突、单位转换和原始资产改动。
- CAD、CAE、联合三种离线记录路径与报告字段；CAE 路径不要求 CAD Design。

## 独立检查与修复

[方法前向检查](skill-forward-check.md) 使用中断任务、厚度变化和历史经验失配的模拟请求。
最终独立源码审查发现并推动修复：

1. 初始已有 task_id 的 Run 不能再归入首次提交队列，现在从 unknown 开始并要求先查询。
2. 派生检索表缺损不能静默表现为无匹配，索引状态须核对原文及派生数据完整性。
3. 演示报告统一使用 artifacts/conditions/gaps，确保成果、条件和未决项出现在专用报告字段。

独立审查代理随后最小复核了上述三项：已知任务拒绝重提、删除 FTS 后拒绝误导性空结果并可重建、
三条演示报告专用字段完整；结论为全部关闭，未发现剩余阻断项。

这些是本地记录和检索一致性证据，不是实际求解成功或模型有效性的证明。

后续补充：使用两篇 NASA 官方教程的真实来源方法/外部数值示例，以及本次真实 CAD 半宽
尺寸反馈，完成三单元的中英文检索、合法关系回读、变更/移除/重登记、失效版本引用和派生库
重建检查。重建前后三单元内容哈希、关系、依赖状态和代表查询一致；6份 CAD 证据副本哈希
与原件相同。报告位于 `workspaces/real-knowledge-validation/validation-report.json`。
算术重算符合 NASA worked example 的公布精度，另列 VERIFY 输出的末位差异，未冒充本地
CFD 求解；两篇教程不替代 AC-16 的完整论文场景，也未证明 AC-18 自主采用。

2026-11-02 后续补充：AC-15 的本地确定性验收已通过独立复核。四种抽取偏好覆盖五个隔离
场景，包括已有知识时跳过；使用保存的真实 CAD 观测，保留完整基础事实、约束和材料警告。
重复物化/登记仍只有一个知识版本，稍后补抽取只使用已存证据，原始 Study/证据哈希不变。
报告见 `workspaces/extraction-preference-validation/validation-report.json`。这不代表用户实际
选择了这些生产偏好，也不证明独立自然语言决策、实机求解或默认密度质量值有效。

另选 Hu et al. (2020), *Metals* 10(5), 688 的完整论文，保存跨章节方法、跨表格实验设计和
有范围限制的 VM2 只读反馈；三单元、六组中英文查询、固定版本关系、完整 Markdown 回读
和四份本地来源哈希检查通过。通用方法读取不会自动载入后端反馈。证据为
`workspaces/full-paper-validation/runs/verified-ny69xbir/validation-report.json`。
来源定位使用 DOI/章节/方程/表格，未宣称保存了原论文 PDF/HTML 快照或迁移了未确认单位
的材料系数；当前仍缺真实求解结果反馈，因此不将本次检索检查计作完整 AC-16 通过。

一次无对话继承的 CAE 研究接续读取现有 Study、协议和参考目标后，没有查询可选知识库。
该结果不证明 AC-18 自主采用历史经验；不为通过验收而补造查询或事后标记采用。实际读取和
建议保存在 `workspaces/history-use-forward/`，AC-18 保持未完成。

## 可复现演示

`python scripts/demo_offline.py --output workspaces/validation/offline-demo-final` 已成功完成。
输出 [演示总报告](../workspaces/validation/offline-demo-final/demo-report.json)，以及
[CAD](../workspaces/validation/offline-demo-final/cad/report.json)、
[CAE](../workspaces/validation/offline-demo-final/cae/report.json)、
[联合](../workspaces/validation/offline-demo-final/coupled/report.json) 的独立工程报告。
各路径均保留原 10 mm 输入、12 mm 后续变更和旧结果影响关系；报告包含成果、条件和未决项。
知识示例登记 3 个单元，英文 pressure 查询命中 2 个、中文层流命中 3 个，来源包可本地读取。

上述运行数据是本地生成证据，未混入可分发 Skill；在新 checkout 可用不同的空输出目录重新生成。
第一阶段本地开发和离线验证完成；之后的真实执行状态以本报告开头链接为准。

## 真实验收边界

第一阶段尚未取得用户 VM/MCP，因此当时真实 AC-01～AC-18 均未执行。后续 CAD 基础链已实测，完整 AC 不因该单件测试自动通过。
离线演示明确记录 `real_mcp_calls: 0`、`engineering_acceptance: not_executed`。
本地测试不代表 M1～M4 真实阶段退出，不证明第二宿主/第二后端兼容性或学术增益。

后续先处理 CAD 执行仓库缺陷并重验，再依据已提供的 VM2 metadata 和现有能力选择 CAE 执行 Skill，按照 [验收说明](acceptance.md) 完成剩余任务；只读 metadata 成功不改变 AC-05/AC-06 等更高层验收仍未完成的状态。
