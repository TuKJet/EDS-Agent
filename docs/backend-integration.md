# 用户后端接入

EDS-Agent 不新增 MCP Server，不提供自制 MCP 通信协议。Codex 使用已配置的 MCP 工具；
本地 `backend` 命令仅检查能力描述、准备参数和规范任务状态，不执行 CAD/CAE 操作。
工具原生语义足够时可直接调用；只为实际单位、标识或状态差异补充绑定。

具体软件操作优先由 `execution-skills/` 下维护中的开源 Skill 承担。EDS 安装器同步 EDS Skill，
按选定执行域检查并应用本地补丁；`--execution none` 只同步 EDS Skill。它不复制上游实现、
不自动安装依赖或改全局设置；执行 Skill 与远程
VM/MCP 连接是两个独立状态。安装检查不等于加载 Skill，加载 Skill 也不等于连接 MCP。
概念讨论和实验设计阶段不读取 vendor 操作细节；冻结实验后按 [可选执行 Skills](execution-skills.md)
的 handoff 路由，具体执行者再加载选定 Skill 和任务能力。明确的安装/排障请求与只读可行性
探测可直接按对应范围进入该执行路由，无需创建研究实验。

## 连接发现与接入信息

正常调用先从 Codex 当前配置和已发现工具读取以下信息；只有发现缺失时才进入安装/排障路由：

- CAD 和 CAE VM：地址/名称、访问方式、系统与工程软件版本、可用许可证。
- 对应 MCP：Codex 中的 server 名称或连接方式、可用工具列表、认证方式，以及安全的凭据配置位置。
- 工作目录和文件传递方式；可以用于验收的已有工程、参考值或测量资料。
- 每次任务和总体验收允许的时间、计算资源、输出目录，以及不能修改的资产范围。

凭据通过宿主配置/环境变量管理，不写入绑定样例、Study 或版本库。
若只提供已连接的 Codex MCP，通常不需要另行登录 VM；VM 访问用于后端排障或补充观察。未发现绑定时，先报告“未发现/未配置”；不可达、认证失败、版本不匹配和工具缺失分别处理，不能直接等同于需要重装。

## 能力盘点与绑定

由 Codex 读取实际工具说明和输入 schema，再填写 `eds-backend/v1` JSON。
`examples/backend.fixture.json` 是语义样例，工具名必须替换为实际发现的工具。
`codex_server` 对应宿主已有连接；它不是地址解析或自动配置指令。

完整能力盘点可检查 CAD 的 inspect/edit/measure/export、CAE 的 inspect/configure/solve/results。
普通任务用 `eds execution ... --capability <name>` 只核对本次能力及必要查询工具，不要求
无关能力齐全。这些名称不是跨所有软件的统一指令集，新动作按实际工具增加。

每个 capability 指定 tool、description 和顶层 inputs。输入映射支持明确类型、required、
target、minimum/maximum，以及数值 unit/backend_unit/scale/offset。
有单位的输入使用 `{"value": 10, "unit": "N"}`，转换系数写在经核对的绑定内；
工具参数不是这些形式时，由实际绑定补齐，不猜测嵌套 JSON 字段或对象标识语义。
未知字段拒绝，避免看似成功但实际丢弃输入。

确认工具只读时，可在该 capability 声明 `read_only: true`；未声明时按有副作用处理。
这一标记来自已经核实的操作语义，不从工具名推断。它允许新的独立观察记录，不允许
忽略仍未决的同一调用，也不改变实际调用前的服务/schema 检查。

```powershell
python -m eds backend local/cae-binding.json check --tools local/discovered-tool-names.json
python -m eds backend local/cae-binding.json prepare solve --data local/solve-input.json
python -m eds backend local/cae-binding.json status solve solving
```

检查只表示配置完整性或与所给工具清单一致，`live_execution` 始终是 `not_verified`。
真实调用、实际状态和结果应写入 Study。发现 HTTP 成功、成功提交或未知状态时，不能映射成任务完成。

## 真实执行与中断

1. 保存 experiment 与精确输入版本，创建 Run（幂等键和输入快照）。本地 evidence 输出路径
   不是 action 输入身份；真正的导出/保存目标仍必须位于工具 arguments 内。
2. 进入 submitting 并持久化，再由 Codex 调用实际 MCP。输出来自工具，不由本地适配器生成。
3. 立即保存返回的原始状态、task_id、模型版本及成果引用。异步调用绑定必须提供 query_tool 和 task_id_field。
4. 已提交、运行中、不确定或提交中断的 Run，恢复后先查询后端。没有 task_id 时查后端任务清单/幂等键，
   无法定位则记录具体缺口；不能因为聊天丢失就重新提交。
5. 回读影响实验含义的实际模型状态，生成 realization 与差异记录。证据引用实际模型、输入与 Run。
6. 工具完成、数值质量和工程解释分开评价。重要偏差先修正实现或收窄结论，再开展下一轮。

本地幂等键约束仅防止重复/冲突的记录，它不能保证远端工具幂等。相同 action 和相同输入状态
已有 `planned` Run 时沿用原 Run 继续提交；已有 `submitting`、`submitted`、`running`、`unknown`
时，客户端返回既有 `run_id/status`、`tool_sent=false` 和 `current_call_not_executed=true`，
先接续查询。绑定明确声明 `read_only: true` 的已完成观察允许同参数再次调用，生成独立 Run
并实际读取当前状态，不返回缓存结果冒充当前观察。明确为 `failed` 且
`preflight_rejected=true, tool_sent=false` 的预检拒绝允许修复后显式再调用，保留原失败记录。
这两种情形仍使用新的本地证据文件，不自动重试。其他终态变更或求解的新动作，至少要传入
此前该动作未使用的固定 evidence 或 realization 引用，不能只替换旧 decision/method 引用或
输出文件名。远端防重和任务查询能力仍应在接入时验证。

## 使用现有官方 SDK 客户端

宿主未暴露目标服务的原生工具时，可以用 `scripts/mcp_call.py` 发出一次由 Codex 选定的请求；它复用用户已有 `mcp/httpx/jsonschema` 运行环境，不实现 MCP 协议或研究循环，也不自动安装依赖。`scripts/invoke_mcp.ps1` 可从本机 DPAPI SecureString 文件临时读取 token，配置只保存 `python_path`、`token_credential_path`、`url` 和 `expected_server`，放在被忽略的 `local/` 中。

```powershell
./scripts/invoke_mcp.ps1 -ConfigPath local/cad-mcp-client.json `
  -OutputPath workspaces/my-study/evidence/inspect-001.json `
  -ToolName solidworks_inspect_native_geometry -ArgumentsPath local/inspect-input.json `
  -StudyRoot workspaces/my-study -ExperimentRef inspect-experiment@1 -InputRefs design@1
```

上述实验和设计引用必须先创建，路径和工具参数须来自本次真实发现。客户端每次初始化后核对 `expected_server`，读取工具清单，用目标 `inputSchema` 验证参数，记录服务名及 schema 哈希；错误服务、缺少工具或非法 schema/参数会在 `call_tool` 前拒绝。原始回复与调用前输入均保留，token不写入记录。summary 的 `tool_sent=true` 只在真实 `call_tool` 返回后设置（包括 MCP API error response）；仅通过 preflight 不算已发送。使用 Study 时 summary 标记 `recording=recorded`；无 Study 的 discovery/call 标记 `recording=unrecorded`，不应当作可恢复的 Run。

客户端把协议错误或明确业务失败（包括 `blocked`）记为失败，传输不确定记为 `unknown`，不自动重提。同一证据路径不能覆盖；不要通过换文件名绕过未知调用的接续检查。若 `invoke` 已开始但 `call_tool` 因超时或断连没有返回，远端是否执行不得臆测，`tool_sent` 与 `current_call_not_executed` 保持 `null`，Run 记为 `unknown` 并要求先查询；只有明确的本地 preflight 拒绝才能报告 `tool_sent=false` 与 `current_call_not_executed=true`。JSON Schema 只校验输入结构，不能检查材料语义、几何正确性或服务器内部实现。

明确业务失败支持 JSON 状态与工具返回的 Markdown 状态标题：首个非空行完整为
`# error`、`# failed`、`# failure`、`# fail` 或 `# blocked` 时记为失败（忽略大小写及行首尾空白）。
说明文字、代码块和后文提到 error 不作为失败标志，原始回复保持完整。可选格式应优先请求 JSON；
任意自由文本不能保证自动判读，工具完成仍须独立评估。历史误分类 Run 保留原状态并追加纠正证据，
不能事后改写已有终态来掩盖错误。

对于异步提交，必须使用已核对的绑定：`mcp_call.py` 的 `--binding PATH --capability NAME`
是一对必须同时出现的参数，且绑定 capability 的 `tool` 必须与位置参数完全一致。绑定中的
`task_id_field` 是相对于解码后 MCP operation payload 的点号路径（例如 `job.job_id`），
`query_tool` 和状态映射仍由调用方维护；客户端不硬编码 Hub 工具名，也不自动查询、重试或循环。
成功提交只记录为 `submitted`（并保存提取的 task id）；缺失、空值或互相冲突的 task id 记录为
`unknown`，打印摘要中的 `requires_query` 为 `true`。工具返回完成并不等于工程验收，仍需后续查询、
实际状态、数值质量和工程解释。
后续状态查询应回写原 Run（按 task id 关联），不会新建提交 Run；客户端不自动轮询。

## 宿主依据

Codex 原生发现仓库 `.agents/skills`，技能正文支持按需读取；实现遵循
[官方 Skills 文档](https://developers.openai.com/codex/skills)（2026-11-02 核对）。
本项目不改宿主源码、不自动写用户级 MCP 设置、不承诺尚未测试的第二宿主或第二后端。
