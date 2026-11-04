# EDS-Agent repository

This repository supplies engineering records and domain methods to Codex.
Codex is the research agent; do not add an embedded model client or a second agent loop.

For engineering tasks, read `skills/eds-study/SKILL.md`, then the relevant
`eds-cad`, `eds-cae`, or `eds-coupled` skill. Load only the references needed by
the current stage: early discussion keeps the goal, hypotheses, observables and
decision rule; a selected, versioned experiment may load the execution handoff;
the execution owner then loads the selected upstream Skill and task capability
notes. Installed copies are discoverable under `.agents/skills`; the `skills/`
directories are the maintained sources.
Use `python -m eds --help` for deterministic record and knowledge operations.
Keep user engineering data and credentials outside the distributable skill directories.

The original requirements are in `doc/`. Implementation notes and actual validation
status are in `docs/`. The latest user instruction authorizes implementation and
selects Codex as the first host, superseding the earlier document-only phase.

Run `python -m unittest discover -s tests -v` and
`python -m compileall -q eds scripts tests` for code changes.
The EDS record core needs no third-party runtime dependency; optional MCP calls use the user's existing official SDK runtime. Keep real MCP execution within the
user-selected backend. Synthetic fixtures never count as real engineering acceptance.

具体 CAD/CAE 执行优先复用 `execution-skills/` 下维护中的 submodule。概念、方法、结果讨论和
实验迭代方案不预加载 vendor Skill、MCP schema 或整套执行手册。冻结实验后，执行者先读
`skills/eds-study/references/execution.md`，由其中 runtime/setup 分流，仅读取所选域上游
Skill 的任务相关章节及能力参考；健康远程 MCP 不加载本机安装、自检或补丁操作手册。
复杂操作可交给受限的 native subagent；主代理保留 Study、假设、判据和下一步决策，只接收状态、
实际偏差、QoI 与证据位置。执行实现继续复用上游；本工程需要的局部适配存入 `patches/`
有序补丁及清单，由安装器核对公开基础提交后自动应用，不要求推送上游或复制整套实现。
安装后执行 `python scripts/install_skills.py --check`；不得用强制 reset 掩盖补丁冲突。
submodule 和本地补丁就绪也不表示 VM/MCP 已同步。这里的冻结指记录实验版本，不是新增审批。
明确要求安装/排障或早期只读能力探测时，也可由执行者进入该路由，只回传所需发现。
知识先按当前问题、其次按阶段选择逻辑类别，再读取固定单元及所需关联；默认不递归展开全文。
个人/团队/项目工程偏好单独以 preference 单元纳管，按作用范围和确认状态检索；
它与经验抽取频率设置不同，不能替代工程依据。规则见 skills/eds-study/references/knowledge.md。
