---
name: eds-study
description: "Guide CAD/CAE study reasoning and continuity: frame alternatives and experiments, interpret evidence, record decisions, and resume work across Codex sessions."
---

# EDS study

Codex owns the engineering decisions; the local `eds` package preserves records.
Start with `python -m eds study <study-path> resume` and the user's question.
This is a compact index, not the full record or an engineering assessment.
Read a selected entity with `show --ref <fixed-ref>` when its content can change
the decision; read a pending Run with `show --run <run-id>` when reconciling it.
Keep the working context to the objective, facts, hypotheses, constraints,
current versions, decision-relevant evidence, uncertainty and next experiment.
Do not use `resume --full`, an unfiltered `show`, or `report` as a startup read.
For routine research, `study.json` is storage, not a reading entrypoint: opening
it directly also bypasses the compact view. Fetch the needed record by its fixed
ref or Run id; inspect the full file only for a specific data-repair/diagnostic need.

## Load only for the current action

The references below are conditional routes, not a startup reading list.

| Current action | Read when needed |
| --- | --- |
| Discuss ideas, methods, results or the next experiment | Only the relevant `eds-cad`, `eds-cae` or `eds-coupled` method. For a joint question start with coupled; do not load all three. |
| Resolve a specific methodological gap | The matching section of repository-root `docs/methods.md`; skip unrelated examples. |
| Create/update records or resume a run | The relevant section of `docs/record-format.md`: current state, entities, Run, evidence, or method-use. Use `python -m eds --help` for the actual operation. |
| Search history | [Knowledge routing](references/knowledge.md): select by current question, then stage; read selected units before expanding relevant relations. |
| Extract or revise reusable knowledge | [Unit contracts](references/knowledge-units.md), only when requested or configured. Personal conventions use the separate preference contract. |
| Execute a recorded experiment | The execution owner reads [execution handoff](references/execution.md); healthy MCP calls use runtime task references, installation/troubleshooting is a separate conditional route. |

Discussion, interpretation and iteration planning do not load vendor manuals,
MCP tool schemas or installation instructions. A feasibility uncertainty may
justify a bounded read-only capability probe by an execution subagent; return
only the supported action, limitations and evidence. Explicit setup/troubleshooting
requests also use the execution route without requiring a research experiment.
Missing connection information first triggers discovery of existing configuration,
not installation. Search history only when it can change the decision; do not load
all collections. Personal preferences are scoped conventions, not physical evidence
or the `once/auto/later/skip` extraction setting.

## Research and continuity

Use one Study; separate facts, assumptions and gaps. Before execution, record the
question, candidates, fixed conditions, changed variables, observations, comparison
rule, budget and expected decision. A recorded experiment version is a dispatch
boundary, not an extra human approval gate.

Keep proposal, actual realization, evidence and assessment distinct. Interpret
tool success, numerical quality and engineering meaning separately. A discrepancy
limits which conclusions the evidence supports. Record changed inputs as new
versions and assess affected results before reusing them.

Concrete execution may use a native subagent with a small task brief. The Study
owner retains hypotheses, acceptance criteria and iteration decisions. Review its
compact result and inspect cited evidence only when needed for the decision;
do not import its manuals, full tool inventory or routine logs into discussion.
On interrupted or unknown runs, reconcile existing work before any new submission.

Keep basic Study/Run/evidence records regardless of optional experience extraction
(`once`, `auto`, `later`, `skip`). Record material method use with version, reason,
affected refs and outcome. Finish or hand off with the current conclusion, evidence,
applicability, gaps and next action or evidence-based stop reason.
