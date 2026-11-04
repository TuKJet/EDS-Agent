# CAE 执行接入盘点

此文是执行阶段按需读取的接入证据，不是研究讨论的启动必读资料。

## 当前决定（2026-11-03）

最新续作：用户已明确允许处理新程序的 TCP 8001 阻断，并要求不备份；实际执行前发现该规则
已是 `Allow`，检查脚本在改写前停止。经 `本机28502 → 宿主18002 → VM2:8001` 的真实
MCP 握手随后通过，返回 `COMSOL MCP` 和 40 个工具。用户同时将 CAE 测试改为通过 MCP
从零创建小型 demo；已记录 `small-thermal-demo-check@1`，采用上游 shared-server 铝块传热
示例，正在核验几何、求解、热平衡、网格和结果输出。此处不再把完整蠕变算例当作前置条件。
最新结果见 [CAE 实机验证](live-cae-validation.md)，下文保留安装与排查经过。

用户已明确：原 Mems MCP 属于另一测试环境，本工程不使用它；改为在 VM2（winvm02）
独立安装开源 CAE Agent Hub 的 COMSOL MCP。后续核对运行时与 Windows 规则确认，新入口
实际是宿主 `18002` → VM2 内 `8001`。
原宿主 `18001` → VM2 内 `8000` 属于同事，保持不动。本地旧 profile 缺少新服务登记，
不能据此判断新端口发布失败，也不再另建 VM 内 `18001` 的发布。
上游固定版本为 `56705e07ce6e99f0d5a0d0c7b5e28b6b2c0bc973`，已加入 submodule。
VM2 已安装到 `C:\Work\eds-cae-hub`，包含独立 Python 3.14.4、venv、上游 COMSOL MCP、
HTTP launcher、锁定依赖、LICENSE 和来源 manifest；43 个依赖经校验后离线安装。

VM2 内部 `http://127.0.0.1:8001/mcp` 的 SDK `initialize`、`tools/list` 已通过，
身份为 `COMSOL MCP`，协议 `2025-11-25`，返回 40 个工具；没有调用 COMSOL 工具。
此检查没有经过宿主 `18002`，不等于外部端到端接入或求解验收。
安装验证后曾停止本次 MCP 进程并移除临时计划任务，当时为 **已安装、未运行**。
主代理随后只读确认安装文件存在、VM 内 `8001` 无监听。该阶段证据见
`workspaces/cae-hub-deployment/eds-cae-hub-smoke-receipt-20261103.json`。

用户当时限定只安装 MCP，安装后停止等待，因为 VM2 仍有其他使用者。此后用户于
2026-11-03 明确表示“我同事用完了，你可以继续了”，已恢复原有验证任务。
续作先启动独立 Hub、核对经宿主 `18002` 的应用连接，再用独立会话和算例副本进行实际
模型检查与受控求解；保留同事原有服务、会话和模型。当前已登记模型准备 Run，尚未据此
宣称外部接入或求解成功，状态以对应执行证据为准。

续作实测：新 Hub 已启动，VM 内握手再次返回 `COMSOL MCP`、协议 `2025-11-25` 和
40 个工具。经正确的宿主 `18002 → VM2:8001` 路径仍超时；宿主 DNAT/SNAT 和发送放行
计数增长，没有收到回复。Windows 的精确 `8001` 放行规则存在，但本次安装目录的
`python\python.exe` 同时有 Public 配置下的 TCP 全端口显式阻断规则。
修复脚本拟先备份、再仅从该程序阻断范围排除 `8001`；自动审批拒绝了这项持久安全设置
修改，已请求用户明确授权，**尚未修改防火墙**。
模型准备改用既有 WinRM 管理通道，在 VM 内以官方 SDK 调用同一个 Hub 的回环地址；
此路径不代表外部 MCP 接入已通过。证据为
`workspaces/cae-hub-deployment/resume-guest-health-20261103.json`、
`resume-root-host-rules-20261103.json`、`resume-root-guest-rules-20261103.json`。

后续通过该 VM 内入口成功启动独立 COMSOL 6.3 两核会话。源文件与独立副本哈希一致，但
COMSOL 明确拒绝加载：安装目录中的算例是案例库预览文件。没有求解或数值结果；完整资产
可用后才能继续物理设置回读。实际 Run、任务编号和证据见[CAE 实机验证](live-cae-validation.md)。

此前 Mems MCP 的模型复制/允许名单修改方案停止执行，薄执行 Skill 草稿也不再作为集成方向。
用户提供新端口并授权安装选定开源服务，不代表授权覆盖另一测试环境的服务、配置或模型。
FEMis 仍仅作为需要时的质量参考。以下 2026-11-02 盘点保留为历史证据，不是新部署指令。

## 历史 VM2 盘点（2026-11-02）

已复用现有宿主/WinRM 安全配置完成 `winvm02` 的 MCP initialize、tools/list、状态及模型库
只读调用。实时身份为 `mems-comsol 0.1.0`，协议 `2024-11-05`，发现 10 个工具。
认证信息只在远端进程内存使用，没有复制到本工程。脱敏探测记录位于
`workspaces/cae-discovery/vm2-probe-20261102.md`；无秘密的复用入口在本地忽略目录。

实时状态报告 COMSOL 6.3、shared plain-JVM engine、两个允许模型 `rf_mems_switch.mph`
和 `creep_stage_a.mph`，以及 18 个 RF MEMS 历史版本。工具还包括 `comsol_model_info`
和 `comsol_build`，比早期静态文档丰富；不能再把旧的参数接口说明当作完整能力清单。
本地 MemsAgent 工程没有现成 `SKILL.md`；存在 MCP 不等于存在可直接安装的执行 Skill。

`comsol_model_info` 曾有一次调用未得到回复体且无 task handle；该历史调用的退出原因仍未知，
保留为 unknown，不把它改写成服务端失败。随后在确认无旧请求在途后完成一次有界只读复试：
现有 WinRM-token + MCP 路径返回 `status=ok` 的模型 metadata，客户端总耗时 33.595 s，
worker 报告 24 s；脱敏诊断记录见
`workspaces/cae-diagnosis/vm2-model-info-diagnosis-20261102.md`。
`comsol_build` 接受已有 Java builder、输出及参数，guest 可见 `CreepModelBuilder.java`；
没有执行 build，不能据工具名称宣称任意建模已通过。最初另一个宿主验收进程占用共享
后端，未干预它的模型或任务；后来确认同一 PID 已消失，当前 MCP 会话的 progress 查询
报告没有后台 job。本工程尚未发起 CAE 求解。

本次成功仅证明固定模型的只读 metadata 回读和当前接入链路可用，不证明 solve、build、export、
物理方案比较、结果驱动修正或工程质量验收；这些仍未执行。

只读源码盘点进一步确认：`CreepModelBuilder.java` 是可重复生成二维矩形模型的真实资产，
具有材料/蠕变参数、载荷、时间序列和 stationary/transient studies，但包含 `study.run()`，
调用 builder 也会执行求解。它还存在 Shell 失败后回退 SolidMechanics 的路径，验收必须
回读实际物理接口，不能把预期的壳表达直接当成已实现。改变尺寸或系数本身不自动构成
AC-03 的不同物理假设。另一个名为 `rf_mems_switch.java` 的文件实际是 MPH ZIP 二进制，
不能当作 Java builder 编译。文件哈希及范围见本地只读源码盘点记录。

## 开源组件的实际边界

| 组件 | 可以复用 | 当前不能据此声称 |
| --- | --- | --- |
| CAE Agent Hub | 各求解器自己的 MCP、配套执行资料和特定任务 Skill | 其 COMSOL MCP 会自动代理 VM2 的 Mems MCP，或仅安装仓库就支持所有建模动作 |
| FEMis | 针对具体质量问题选择的检查方法/计算参考 | 它是求解器驱动或 MCP 服务，或其整套工作流应在所有研究讨论前加载 |
| VM2 Mems MCP | 确认 live schema 后可复用的既有远程任务服务 | 参数扫描等于物理模型方案比较，或静态工具说明证明当前远端能力 |

Hub 的 COMSOL MCP 自行通过 MPh/Java bridge 操作 COMSOL；它的工具名、参数和任务语义
与 Mems MCP 不同，并非通用 MCP client。公开工具支持打开/保存模型、参数、study 求解、
表达式求值、导出及部分摘要；创建空 model 不等于建立了完整物理模型。
`comsol_run_shared_script_tool` 是调用已有脚本的入口，脚本所实现的建模与回读能力仍需单独验证。
参见上游 [COMSOL MCP 文档](https://github.com/Cai-aa/CAE-Agent-Hub/blob/main/MCP/COMSOL/README.md)
及 [工具定义](https://github.com/Cai-aa/CAE-Agent-Hub/blob/main/MCP/COMSOL/mcp_server.py)。

Hub 现有 [COMSOL motor NVH Skill](https://github.com/Cai-aa/CAE-Agent-Hub/blob/main/Skill/comsol/comsol-motor-nvh-evidence/SKILL.md)
面向永磁电机 NVH，不能直接把它作为 MEMS 或梁的执行说明。
[FEMis](https://github.com/test1card/femis-skill/blob/main/SKILL.md) 的质量参考按具体检查取用；
不把其完整人类决策流程替换成 EDS 的默认研究过程。

## 集成决定及验收缺口

保留“EDS 研究与连续性 → 选定执行 Skill/MCP → 按需质量检查”的分工。
目前不把两套仓库同时接成默认执行依赖；先验证实际服务和所选任务能使用的上游入口，
再以独立 submodule 固定可复现版本。具体实现不复制进 EDS。

仅做固定模型的参数扫描，不能满足 AC-03/AC-05 要求的实质不同物理假设及结果驱动修正。
后续需要可表达这些假设的版本化模型或建模能力，并能回读影响结论的方程/接口、材料、
边界、网格和求解状态。新增执行能力应维护在相应上游仓库，不能用 EDS 中的临时求解代码补齐。
现有模型和参数白名单保持有效；不通过扩大权限来掩盖能力缺口。

下一步是检查已有 builder/模型是否覆盖所选物理假设，再固定真实 CAE 任务、阈值、预算及执行入口。
认证和 metadata 回读缺口已解决；CAE 求解、物理方案比较及联合闭环仍未执行。

## 后续具体化：官方算例与薄执行 Skill

已从实际源码确认，现有 creep builder 固定创建时间硬化蠕变；RF MEMS 模型同时包含
SolidMechanics 与 Electrostatics，不能把两个不同任务的模型直接当作受控物理方案对比。
现有 `comsol_run` 支持命名表达式提取，`comsol_export` 支持 CSV 输出，但本地尚未完成求解验收。

VM2 已有官方 `variable_load_creep.mph`，可复用同一算例中的时间硬化与应变硬化假设、
受控阶跃载荷和解析目标曲线。依据是 COMSOL 6.3 的
[变载荷蠕变算例](https://doc.comsol.com/6.3/doc/com.comsol.help.models.nsm.variable_load_creep/variable_load_creep.html)。
已登记独立 CAE Study、两项提议、方法使用记录和计算预算，见
`workspaces/live-cae/study/study.json`、`workspaces/live-cae/protocol-draft.json`。
这仍是实验准备，没有将解析值当作本地 COMSOL 输出，也没有宣称哪种假设更符合真实材料。

实际服务每次读取 `allowlist.txt`，新算例只需独立副本和一个明确文件名的条目，不需要修改
服务代码或重启。预备目标是 `eds-variable-load-creep-20261102.mph`。该持久设置被自动审批
拒绝，理由为原用户任务未明确授权此项模型允许名单修改；已经请求用户明确确认，尚未执行。
本地准备脚本经过 PowerShell 5.1/7 共 16 项文件操作检查；它们不代表 VM 配置或求解已经成功。

针对当前 Mems MCP，已编写独立的薄执行 Skill 草稿
`local/mems-comsol-skill-draft/`，只包含新编写的执行约定，不复制私有 MemsAgent 代码，
不新增模型客户端或求解实现。公开独立仓库或私有接入的来源选择待用户答复；草稿尚未发布、
安装为 submodule 或通过实机求解验证。Hub/FEMis 仍不是该服务的默认执行依赖。
