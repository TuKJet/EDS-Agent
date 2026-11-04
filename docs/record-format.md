# EDS-Agent 工程记录格式

`StudyStore` 是 Codex 使用的确定性文件工具。一个独立工程工作区保存
`study.json`；它不决定研究路线、不调用模型、不提交 MCP 请求。
以下为 `eds-study/v1` 的实际接口。Python 要求 3.11+，不需要第三方依赖。

## 持久性与变更规则

每次修改取得操作系统文件锁，重新读取并验证最新状态，将完整 JSON 写入同目录
临时文件并刷新到磁盘，再原子替换。写入或替换失败时，先前工程文件保留。
`.study.lock` 是持久哨兵文件；**文件存在不表示锁被占用**。Windows 字节锁及
POSIX 文件锁随进程退出自动释放，进程异常终止不会遗留需要人工删除的逻辑锁。
这些约定面向本地文件系统；网络文件系统上的锁和原子替换行为需要单独验证。

实体只能追加修订，不能通过工具覆盖旧版本。Run 的输入不可修改，状态观察追加到
`history`。摘要、事实、偏好及指标更新保留前值和改动事件。读取也验证 schema、
版本、引用种类、任务历史和有限 JSON 数值；损坏文件会明确报错，不静默重建或丢弃事实。
文件仍属于用户可编辑资料，这些校验不构成防篡改签名或备份。

## 工程初始化和当前状态

```python
from eds import StudyStore

study = StudyStore.create(
    "workspaces/bracket", "比较支架表达的尺寸变化行为", mode="cad",
    constraints=["保留装配接口"],
    facts=["已读取用户提供的原生工程"],
    assumptions=[],
    gaps=["材料牌号尚未提供"],
    assets=[{"uri": "asset://bracket/native", "version": "revision-1", "unit": "mm"}],
)
```

`mode` 为 `cad`、`cae`、`coupled`；兼容输入 `joint`，保存为 `coupled`。
CAD 独立任务不需要 CAE 对象；CAE 独立任务不需要 CAD 设计。

- `read()` 返回完整验证过的记录副本。
- `update_context(**values)` 更新 `goal`、`mode`、`constraints`、`facts`、
  `assumptions`、`gaps`、`assets`；其他字段保存到 `context`。
- `set_summary(**values)` 仅更新 `context`，通常写 `next_step`、`conditions`、
  `artifacts`、`stop_reason`、预算、当前问题和检索状态。
- `resume()` 默认返回精简索引：事实、假设、资产、当前对象与最新评估/决策的固定版本引用、
  未终结和失败任务的身份/状态、研究摘要及下一步。它不自动解释原始数据，也不等于评估结论。
  对象 payload、Run 输入快照、历史和原始输出留在完整记录中。
- `get_run(run_id)` 读取一项完整 Run；`get(ref="固定引用")` 读取所选对象。
  `resume(full=True)` 可显式读取原有详细接续视图；不要把它当作日常启动摘要。
- `render_report()` 返回当前设计/提议/实现/映射、原始证据、评估、成果引用、
  成立条件、未决问题和停止理由。缺失停止理由保留为 `null`，工具不替 Codex 作出结束判断。

接续时先读索引，再按当前判断需要读取个别对象或任务：

```powershell
python -m eds study ./workspaces/bracket resume
python -m eds study ./workspaces/bracket show --ref bracket@1
python -m eds study ./workspaces/bracket show --run <实际run_id>
```

摘要中的 `context` 只包含 `current_question`、`conclusion`、`conditions`、`next_step`、
`stop_reason` 和 `budget`；其余字段名列在 `omitted_context_keys`，不会删除保存的数据。
请将影响判断的失败、实际偏差和未知项写入研究摘要/评估，并保留相应证据引用，
不要把 schema 或常规日志当作研究摘要。摘要保留 unknown/submitting 的查询队列和
失败 Run 的定位信息，但原始错误需要按 Run 读取；缺少已读错误不能解释为没有错误。
完整调试/导出可用 `resume --full`、`show` 或 `report`，不作为日常接续的默认阅读动作。

## 实体、版本和关系

```python
design = study.add("design", {"name": "baseline", "thickness_mm": 10}, ref="bracket")
proposal = study.add("proposal", {
    "purpose": "测试厚度修改后接口定位是否保持",
    "assumptions": ["接口面保持同一语义"],
    "design_ref": "bracket",
}, ref="stable-interface")
```

返回实体的 `logical_ref` 为稳定名称，如 `bracket`；`ref` 为不可变版本身份，如
`bracket@1`，`version` 为正整数。再次 `add(..., ref="bracket")` 创建下一版本。
`get(ref="bracket")` 返回最新版本，`get(ref="bracket@1")` 返回当时版本。
`get(kind="evidence")` 返回所有证据修订。传入固定版本作为新修订的基底时，例如
`add(..., ref="bracket@1")`，该版本必须仍为最新版本，避免无意覆盖其他会话的新判断。

可用种类及最小必需字段如下；领域相关内容继续放入 payload，不建立跨软件的通用物理 schema。

| 种类 | 最小字段 |
| --- | --- |
| `design`、`mapping`、`decision` | 非空 JSON 对象；Codex 负责提供用途所需的设计、对应及理由 |
| `proposal` | 非空 `purpose`、列表 `assumptions` |
| `experiment` | 非空 `question`、非空列表 `observations`、非空 `decision_rule` |
| `realization` | 指向 proposal 的 `proposal_ref`、实际 `observation`、列表 `differences` |
| `evidence` | 可定位的 `source` 文本或对象、实际 `observation`；工具执行的证据应另写 `run_id` |
| `assessment` | 非空 `evidence_refs` 列表、非空 `interpretation`、非空 `next_action` |

只把下列**顶层字段**当作内部依赖：`refs`、`input_refs`、`candidate_refs`，以及
每个实体种类的 `<kind>_ref` / `<kind>_refs`。写入时，逻辑引用立即固定为已存在的版本；
带种类名称的字段还检查目标种类，例如 `evidence_refs` 不可指向 design。
`run_id` / `run_ids` 必须指向已有 Run。

外部引用如 `source_ref`、`asset_ref`、`knowledge_refs` 不会被解析为内部实体。
可以在它们中保存文件路径、URI、内容哈希、知识单元版本及来源定位。
嵌套对象不自动形成依赖；需要参加变更传播的对象应另写到上述顶层关系字段。
同一逻辑名称不能在修订时改变种类。

## 实验和 Run

先保存要回答的问题和判据，再登记提交意图：

```python
experiment = study.add("experiment", {
    "question": "厚度变化是否破坏接口定位？",
    "candidate_refs": [proposal["ref"]],
    "observations": ["接口引用状态", "厚度回读值"],
    "decision_rule": "接口语义不变且回读厚度符合本次输入时保留表达",
    "conditions": {"requested_thickness": {"value": 12, "unit": "mm"}},
    "budget": {"mcp_call_limits": {"edit-and-inspect": 2}},
}, ref="interface-test")
run = study.add_run(
    experiment_ref=experiment["ref"], input_refs=[design["ref"], proposal["ref"]],
    backend="user-selected-cad", capability="edit-and-inspect",
    input_snapshot={"thickness": {"value": 12, "unit": "mm"}, "asset_version": "revision-1"},
    idempotency_key="interface-test-round-1",
)
study.transition_run(run["run_id"], "submitting")
# 由 Codex 在此调用真实 MCP。以下操作使用实际返回的 task_id / response：
# study.transition_run(run["run_id"], "submitted", task_id=task_id, output=response)
```

Run 保存不可变的实验版本、输入版本、输入快照、后端、能力和初始任务身份。
同一 `idempotency_key` 及同一请求返回原记录；任一请求字段不同则拒绝。
后续查得的任务 id 不改变最初请求身份。一个后端任务不能关联到两个 Run。
这只是本地记录幂等，不能替代后端自身的请求幂等保证。

`experiment.payload.budget.mcp_call_limits` 可为实际 MCP 工具名设置非负整数最大尝试数（0 表示禁止调用）。
`add_run` 在同一 Study 写锁内检查并预留额度；planned、submitting、submitted、running、
unknown 以及已实际发出的失败均占用额度。明确从未进入 submitting 的 cancelled Run 释放
预留；超时或缺失发送证据不会释放。没有配置该字段时保持原有语义，历史 Run 不会被追溯计入
新预算。达到额度时调用 helper 在网络前拒绝，返回 `preflight_error=mcp_attempt_limit`，
不会调用 MCP 工具。

同一冻结 experiment、工具、服务和 arguments 的终态变更或求解，不能仅通过替换旧
decision/method 引用重试；新动作至少要带一个此前该动作未使用的固定 evidence 或
realization 引用。绑定明确声明 `read_only: true` 的已完成观察可生成新 Run 再次实际读取；
`failed` 且 `preflight_rejected=true, tool_sent=false` 的未发送失败可修复后显式重试。
旧 Run 的历史保留，每次调用最多发送一次；pending/unknown 仍先查询。这些规则只约束动作
记录，不证明任何物理状态；状态真假仍由 Codex 根据实际查询和证据判断。

接管已经存在的后台任务时，使用同一个 `add_run(..., task_id="实际任务编号")`
登记已知输入。此时首条记录和初始状态均为 `unknown`，立即进入查询待办，不能再次
转入 `submitting`。查到实际状态后可以更新为 `running` 或带实际输出的 `completed`。
只有未提供初始任务编号的新意图才从 `planned` 开始。初始化未知任务不会伪造一次新的提交。

| 当前状态 | 允许的后续状态 |
| --- | --- |
| `planned` | `submitting`、`cancelled` |
| `submitting` | `submitted`、`running`、`completed`、`failed`、`unknown`、`cancelled` |
| `submitted` | `running`、`completed`、`failed`、`unknown`、`cancelled`；同状态新观察 |
| `running` | `completed`、`failed`、`unknown`、`cancelled`；同状态新观察 |
| `unknown` | 查询确认后的 `submitted`、`running`、`completed`、`failed`、`cancelled`；同状态新观察 |
| `completed`、`failed`、`cancelled` | 终态，不重新打开 |

每次 `transition_run(run_id, status, *, output=None, task_id=None, observed_at=None)`
追加状态、带时区的观察时间、当时任务 id 和原始输出。重复查询仍为 `running` 或
`unknown` 时也保留新观察。已知 `task_id` 不可更换。
`completed` 必须提供此次实际输出，不能仅因 HTTP 请求成功填入完成状态。
同步工具可从 `submitting` 直接完成。操作完成不代表模型质量或工程有效性通过。

`resume()` 的 `ready_to_submit` 只包含从未进入提交阶段的 `planned` 意图；
`query_before_submit` / `query_before_resubmit` 包含其余未终结 Run。
即便 `submitting` 没有任务 id，也必须先尝试用后端日志、请求标识或资产状态查明情况。
无法查明时保存缺口并继续独立分支；`unknown` 无法回到 `submitting`。
工具不自动网络重试，不假定任务丢失。

## 实际实现、原始证据与判断

```python
# actual_state 与 raw_result 必须来自实际回读；此处不提供伪造的执行结果。
# realization = study.add("realization", {
#     "proposal_ref": proposal["ref"], "run_id": run["run_id"],
#     "observation": actual_state, "differences": differences,
# })
# evidence = study.add("evidence", {
#     "run_id": run["run_id"], "realization_ref": realization["ref"],
#     "source": {"uri": result_uri, "version": result_version}, "observation": raw_result,
# })
# study.add("assessment", {
#     "evidence_refs": [evidence["ref"]], "interpretation": interpretation,
#     "next_action": next_action, "applicability": applicability,
# })
```

原始证据不应写成模型内部推理；评估记录对证据的解释、限制和下一步。
实际模型偏离提议时，保留 `differences`，修正实现或按实际条件解释结果。

`impact("bracket@1")` 从指定版本追踪实体关系、Run 输入、Run 关联证据和后续评估。
返回 `affected`、`affected_runs`、`old_results_require_review`。
新版本不会覆盖或自动使旧结果成为当前证据；是否能复用由 Codex 根据实际变化判断。
若要分析旧版本改变的影响，应传入旧版本引用，而不是已指向新版的逻辑名称。

## 指标、方法使用与可选抽取

这里的 `preferences` 只表示是否抽取经验。个人/团队/项目的建模、标注和交付偏好以独立
`type=preference` 知识单元保存，带 scope、scope_id、确认状态和来源；详见
[工程偏好](../skills/eds-study/references/preferences.md)。它们不是 Study 抽取频率的额外取值。

`set_metrics(**values)` 支持 `elapsed_seconds`（有限非负数）、`human_inputs`
（非负整数）和 `model_cost`（带币种、金额和来源等内容的对象）；未知值均为 `None`。
实验数、实验修订数、Run 数及完成/失败/未知数量由记录计算，不能由调用者直接修改。
耗时和模型费用不是从聊天时长猜测得出，调用者需写明可用测量。

方法加载、历史检索、采用/限制/拒绝可用 `decision` 实体保存，引用外部方法路径、内容哈希、
知识单元版本和影响的内部 `refs`。完整上下文仍由 Codex 负责撰写。

```python
study.set_preferences("auto")
study.record_extraction(["method-interface@1", "feedback-interface@1"], event_key="round-1")
# 用户稍后要求补抽取，即使偏好为 later / skip，仍可以记录本次明确请求：
study.record_extraction(["feedback-interface@2"], event_key="backfill-1", explicit=True)
```

准确签名：`record_extraction(unit_refs, *, event_key=None, explicit=False)`。
单元引用必须含 `@version`。省略 key 时由规范化单元集合生成稳定 key。
重复 key 和相同单元版本返回原事件，重复 key 指向不同单元版本则拒绝。
`auto` 支持多个阶段；`once` 成功保存一个事件后回到 `later`；`later` / `skip`
不自动记录额外抽取，但 `explicit=True` 支持当前用户要求的补抽取。
基础工程记录始终保存，不依赖抽取偏好。该事件表示 Markdown 已由 Codex 产出并引用，
不宣称知识单元已登记或已可检索；知识库工具分别报告这些状态。

## 本次内核加固与验证

加固顺序为：先增加版本、幂等、任务观察、关系传播、偏好和损坏状态的失败回归；
再替换锁与记录实现；最后验证多线程、多进程、进程崩溃和原子替换失败。
`tests/test_study.py` 覆盖上述确定性行为。真实 CAD/CAE 执行和工程有效性仍须 VM/MCP 验收。
