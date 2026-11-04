# EDS-Agent

工程设计与仿真研究工具包。Codex 直接负责理解目标、提出方案、选择实验、调用用户 MCP、
评价结果及提取经验；本仓库提供确定性的记录和检索工具，不内嵌第二个模型或 Agent 循环。

已提供 CAD 独立、CAE 独立及联合方法、版本化工程记录、任务接续、变更影响、
Markdown 知识单元和 SQLite 中英文检索。真实 CAD/CAE 验收需接入用户的 VM/MCP；
离线示例不代表真实工程操作通过。

## 本地使用

需要 Python 3.11+（当前验证环境为 Python 3.14）。EDS 记录与检索核心无第三方运行依赖；实际执行另需所选 Skill 和 MCP 的运行环境。

### 给安装 Agent 的步骤

安装完整工程时同时初始化执行 Skill 的 submodule：

```powershell
git clone --recurse-submodules https://github.com/TuKJet/EDS-Agent.git
cd EDS-Agent
```

已有 checkout 则在仓库根目录执行：

```powershell
git submodule update --init --recursive -- execution-skills/solidworks-automation-skill execution-skills/cae-agent-hub
git submodule status
```

CAD 执行依赖 `execution-skills/solidworks-automation-skill/SKILL.md`，来自 `vm-sw-automation-skill` 分支，按主仓库 gitlink 锁定版本。
gitlink 固定公开基础提交，工程所需适配由本仓库 [patches/](patches/README.md) 保存，安装时自动应用；不要求把这些改动推到上游。补丁只保存差异，版本与验证边界见[执行 Skills](docs/execution-skills.md)。
使用 ZIP 下载而缺少 submodule 时，不能报告 CAD 安装完成；应取得带 submodule 的 Git checkout。
CAE 使用开源 CAE Agent Hub，源码已加入 `execution-skills/cae-agent-hub` 并固定版本。其通用 COMSOL MCP 文档为 `MCP/COMSOL/README.md`；正常调用只读取当前工具相关段落，安装时再读部署部分。仓库内 motor NVH Skill 仅适用于对应任务，不当作通用 CAE Skill。纯记录或离线任务可以省略执行端。

接着安装并核对 EDS 方法：

```powershell
python scripts/install_skills.py
python scripts/install_skills.py --check
python -m eds doctor
python -m eds study ./workspaces/my-study init --goal "研究支架的建模表达" --mode cad
python -m eds study ./workspaces/my-study resume
```

安装会复制本工程的四个 Skills 到仓库 `.agents/skills/`，并自动核对、应用已初始化执行 submodule 的登记补丁；不更改全局 Codex 配置。
重复安装会识别已应用补丁；`--check` 只检查，待应用、版本不符或额外修改会返回失败。不要用强制 checkout/reset 绕过冲突。
只安装记录方法可用 `--execution none`；只需某个执行端时用 `--execution cad` 或 `--execution cae`，此时对应 submodule 缺失会报错。默认 `auto` 允许跳过未初始化的可选执行端，安装 Agent 必须据此报告缺口。
技能正文引用仓库文档，因此应保留完整 checkout；不要只复制一个 Skill 到其他项目。
可选的软件执行 Skill 或 MCP 实现放在 `execution-skills/` Git submodule 中，不复制其实现；安装结果分别报告 Skill、MCP 实现文档和初始化提示。当前 CAD 使用 `solidworks-automation-skill`，CAE 使用 CAE Agent Hub 的 COMSOL MCP；两者都须核对实际部署与任务适用范围。
Codex 可以直接读取本仓库 `AGENTS.md` 与技能源文件。原生发现由宿主负责，若未显示需刷新宿主。

**执行端安装验收：** 安装 Agent 先初始化对应 submodule，运行安装器并通过 `--check`，确认登记补丁已应用；只有在配置或验收该执行端时，才读取所选 submodule 的 `SKILL.md` 和安装/能力说明，并按其指引配置 MCP。普通研究讨论不会重复加载执行手册。可复用用户已有远程 VM/MCP；本地补丁不会自动部署到 VM。远端 MCP 必须部署这份已校验的补丁源码，或在远端取得本工程后运行同一安装器；单独拉取原始上游仓库不包含 EDS 补丁。部署后还须核对实际文件指纹、运行进程加载的版本，并验证具体操作。
EDS 的 CAD/CAE 方法会按阶段引导 Codex 加载执行 Skill，不依赖宿主自动发现嵌套 submodule；Skill 文档不自行发起 MCP 请求。
取得真实工具清单和本地绑定后，可针对本次需要的能力做轻量核对：

```powershell
python -m eds execution cad --backend local/cad-binding.json --tools local/cad-tool-names.json --capability inspect
python -m eds execution cae --backend local/cae-binding.json --tools local/cae-tool-names.json --capability results
```

普通检查只核对所选域、当前能力和记录的工具清单，不重建补丁、不检查其他后端，也不要求本次不用的全部领域能力。省略 `--capability` 时检查绑定中已声明的能力。安装、升级或源码排障时加 `--maintenance`，才检查所选执行源的固定版本、工作树和补丁；`--full` 只控制输出详情。实际调用仍须核对服务身份与目标工具 schema；本地检查不宣称 MCP 连通或具体操作通过。
分别报告「EDS 方法已安装」「执行 Skill 已加载」「MCP 已连接」「具体操作已验证」；未通过的阶段注明缺口，不统称安装成功或执行可靠。
凭据留在用户现有安全配置中。完整接入约定见 [执行 Skills](docs/execution-skills.md) 和 [后端绑定](docs/backend-integration.md)。

### 逐级读取与执行委派

先用 `eds-study` 和当前领域方法讨论目标、假设、候选和判据；联合问题先读 `eds-coupled`，不默认叠加所有方法。实验版本和固定输入确定后，执行者再读取[执行交接约定](skills/eds-study/references/execution.md)，只加载所选执行 Skill 的相关能力。这里的版本确定不是新增审批步骤。

执行者先发现已有连接和绑定。健康 MCP 使用[正常调用入口](skills/eds-study/references/execution-runtime.md)，只读取上游任务章节和参考；确认存在配置、连接或兼容性缺口时才进入[安装排障入口](skills/eds-study/references/execution-setup.md)的对应分支。未发现信息不等于未安装，不可达不等于需要重装；远程服务调用不要求在调用者本机安装 CAD/CAE 依赖。

复杂操作可交给使用独立上下文的原生 subagent，只传递本轮任务、固定输入、判据、预算和操作范围。主代理接收状态、实际偏差、观测量及单位、证据位置和待决策事项；完整手册、schema 和常规日志留在执行端。结果讨论只按需追读具体证据或质量参考，失败检查和未知状态不能在压缩中丢失。

接续命令 `resume` 默认只返回研究摘要、版本引用和任务状态，避免把执行历史重新灌入主对话。
需要核实某个结果时用 `show --ref <固定引用>`，执行者核实任务用 `show --run <run_id>`；
`resume --full` 保留完整接续视图，供明确需要详细记录时使用。
日常研究不要在摘要之后直接打开整个 `study.json`，这会重新载入全部记录；按引用取所需对象，完整文件仅在具体数据修复或诊断时查看。

在 Codex 中可请求：

> 使用 eds-study 和 eds-cad 接管 workspaces/my-study，先读取工程现状，提出能区分的候选并保存实验意图；确定实验后再加载对应执行 Skill，依据真实结果继续。

知识库位于独立目录，只收录明确登记的 Markdown 单元。格式与完整示例见
[知识示例](examples/knowledge/README.md)，不自动扫描磁盘或将 `doc/` 当作用户知识库。

```powershell
python -m eds kb ./workspaces/knowledge register method.md
python -m eds kb ./workspaces/knowledge route --question method-selection --stage planning
python -m eds kb ./workspaces/knowledge search "层流 pressure" --question method-selection --limit 5
python -m eds kb ./workspaces/knowledge read method-fluid-gap --version 1
python -m eds kb ./workspaces/knowledge read method-fluid-gap --version 1 --relation tested_by --depth 1 --max-units 5
python -m eds kb ./workspaces/knowledge sync
python -m eds kb ./workspaces/knowledge rebuild
```

`method.md` 必须已经存在于指定知识目录并符合元数据约定。Markdown 保留事实与来源，
SQLite 为可重建派生数据；库不可用时 Codex 可继续使用当前工程和直接资料。

知识分为设计思路、方法、实验方案、验证反馈和工程偏好五种逻辑类别，共用现有存储。
先按具体问题选类，阶段作为后备，再结合领域、项目和用户范围检索；零命中不会自动扩成全库搜索。
默认回读只含选中单元全文与关联定位，相关正文需显式读取。旧无路由搜索保留为主动全库检索入口。
工程偏好单独记录使用者、适用范围和确认状态，日常检索只采用范围匹配的已确认条目；
它与 `once/auto/later/skip` 抽取频率不同。完整说明见[知识路由](skills/eds-study/references/knowledge.md)、
[分类纳管](skills/eds-study/references/knowledge-units.md)及[偏好管理](skills/eds-study/references/preferences.md)。

## 验证与执行接入

```powershell
python -m unittest discover -s tests -v
python -m compileall -q eds scripts tests
python scripts/demo_offline.py --output ./workspaces/offline-demo
python -m eds backend examples/backend.fixture.json check
```

离线演示生成三种 Study、执行状态历史、手动变更及影响报告、知识登记和检索结果。
`backend.fixture.json` 中所有工具名均为示例，不能直接作为真实工具配置。

- [工程记录与 API](docs/record-format.md)
- [后端绑定与 VM 信息](docs/backend-integration.md)
- [可选执行 Skills](docs/execution-skills.md)
- [三条路径验收与需求映射](docs/acceptance.md)
- [本地验证报告](docs/validation-report.md)
- [逐级披露与知识路由验证](docs/disclosure-and-knowledge-validation.md)
- [运行时检查精简与工程图路由验证](docs/runtime-lightweight-validation.md)
- [当前交付与剩余验收](docs/delivery-status.md)
- [CAD 实机验证与缺口](docs/live-cad-validation.md)
- [CAD 修复与候选复验](docs/live-cad-repair-validation.md)
- [CAE 实机验证](docs/live-cae-validation.md)
- [CAD/CAE 联合验收记录](docs/live-coupled-validation.md)
- [领域方法与解析自检](docs/methods.md)

开发依据是本地 `doc/` 需求；原目录保持原有 Git 忽略约定。可分发的实现说明在 `docs/`。
用户工程、原生文件、实际知识和私密后端配置应保存在独立工作区；`workspaces/` 和 `local/` 已忽略。
历史验证报告中的 `workspaces/` 成果与原始日志链接指向本地留存证据，不随 GitHub 仓库分发；
公开仓库保留验证摘要、测试及合成示例，可按上面的命令进行本地功能验证。
