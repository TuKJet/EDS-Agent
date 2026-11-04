# 可选执行 Skills

EDS 的四个 Skills 负责工程目标、候选、实验、状态、证据和评估。具体 CAD/CAE 软件操作优先复用维护中的开源执行 Skill，不在本仓库复制实现，也不在安装 EDS 时自动安装其依赖或写入全局 Codex/MCP 配置。

## 加载时机

执行端有三个独立阶段：

1. **正常调用**先发现当前 Codex/MCP 绑定，核对服务身份、目标工具 schema 和最小版本状态。连接健康时只读取任务相关能力参考，不读取安装、补丁或部署历史。
2. **安装/排障**是独立路由：只有确认未配置、缺少执行源、认证失败、服务不可达、版本不匹配或能力缺失时，才读取对应 setup/patch 资料。明确提出安装或排障时可直接进入该路由。
3. **实验冻结**后，读取 `skills/eds-study/references/execution.md` 中的任务交接约束；具体执行通过 [runtime 索引](../skills/eds-study/references/execution-runtime.md) 选取所选域 submodule 的 Skill 任务章节和能力参考。若上游只提供通用 MCP，则只读取当前工具相关文档段落。复杂操作可由 native subagent 独立执行；主代理不把完整手册、schema 或原始日志重新载入研究上下文。

“冻结”指保存实验版本，不增加用户审批步骤。明确要求安装、配置、排障时可直接进入相应执行资料，无需先建立研究实验。早期若只需判断可行性，可做只读能力探测并返回限制；不能借此提交修改或求解。主代理始终拥有研究假设、比较规则、版本关系和下一步决策，执行者回传状态、实际实现差异、QoI、证据路径和未知项。

安装或排障路由才读取以下维护信息。执行 Skill 作为 `execution-skills/` 下的 Git submodule 接入。CAD 使用 `solidworks-automation-skill`，来源为 `https://github.com/TuKJet/solidworks-automation-skill.git`，基础分支 `vm-sw-automation-skill`。gitlink 固定公开基础提交 `8a572ce6fa4d78e6ee75f03cc14547cf94830d8a`，本工程适配由 [补丁清单](../patches/solidworks-automation-skill/manifest.json) 按顺序应用。VM 部署与工程复验以[实际复验报告](live-cad-repair-validation.md)为准。安装步骤：

```powershell
git submodule update --init --recursive
python scripts/install_skills.py
python scripts/install_skills.py --check
```

也可以通过 `git clone --recurse-submodules` 获取完整工程。安装器先在临时目录完整重建补丁，核对每步文件内容，再写入 submodule；重复安装不会重复打补丁。工作树出现清单规定的差异是正常状态，额外修改、错误基础版本或补丁校验失败会阻断。更新时须同时审查上游变更、刷新 gitlink 与补丁基础/内容哈希并重新测试；不盲目追踪远端分支。维护与恢复说明见 [patches/README.md](../patches/README.md)。

普通调用可按任务做轻量绑定检查（不联网、不调用 MCP）：

```powershell
python -m eds execution cad --backend local/cad-binding.json --tools local/cad-tools.json --capability inspect
```

普通检查只核对所选域和本次能力的具体工具，不读取 Git 状态或重放补丁。缺少本次不用的领域能力不阻断目标操作。所需任务指引仍按 runtime 索引读取；来源缺失时明确报告指引缺口。通过不代表 MCP 已连通、宿主已自动发现或几何结果有效。

首次安装、升级或源码维护时，用同一命令加 `--maintenance --full`，检查所选 submodule 的固定提交、工作树和补丁。维护检查不扫描另一后端；`--full` 本身不触发维护检查。纯记录或方法安装的 `--execution none` 不核验任何执行补丁。

提示可选执行 Skill 不等于已连接 VM/MCP，也不等于执行仓库与远端部署同步。通用实现继续跟随源仓库，本工程的适配差异由 `patches/` 管理。部署时记录公开基础提交、补丁清单 SHA-256 与远端实际文件指纹；只更新本地 submodule 不算更新 MCP。

`execution-skills/cae-agent-hub` 来源为 `https://github.com/Cai-aa/CAE-Agent-Hub.git`，固定到公开提交 `56705e07ce6e99f0d5a0d0c7b5e28b6b2c0bc973`。其通用入口是 `MCP/COMSOL/README.md` 和 `MCP/COMSOL/mcp_server.py`，安装检查将其报告为 MCP implementation，`task_skill_path` 为空；motor NVH Skill 仍只适用于电机任务。

取得实际绑定和工具清单后可运行 `python -m eds execution cae --backend <binding.json> --tools <tool-names.json> --capability results`。普通检查只说明该任务的绑定和工具清单可用，不表示源码维护、服务连通或求解通过。FEMis 可按需提供质量参考。当前实际验收证据见[CAE 接入盘点](cae-execution-selection.md)。
