# Bounded execution handoff

## Activity preset handoff

Before a modeling-view, result-plot, animation or export plan is frozen, resolve
the actual user's applicable presentation preference or active preset once. If
no matching preset exists, retrieve confirmed scoped preferences explicitly and
compile a named preset. Do not wait until final delivery to load the convention.
Include its immutable task snapshot in the Run input plus concrete readability
checks: identifiable structure/material/region; physically meaningful direction;
quantity, units, scale and time semantics; comparison consistency; source binding;
and representative-frame/final-media visual inspection. Unsupported display
settings remain explicit in the handoff and require a supported presentation route,
not silently omitted requirements. This is an owner-enforced handoff obligation,
not a claim that every external MCP tool automatically injects preference memory.

If an activity preset is selected, include its fixed task snapshot in the task
brief: preset name, context, revision/hash, source preference refs, effective
values, and task overrides. Do not re-run knowledge search during each Run;
record the snapshot in the Run input so a batch remains reproducible. Map style
values only to fields supported by the selected vendor `DrawingSpec`. Return
applied and unmapped settings separately. Units, projection, true dimensions,
associativity and required manufacturing information remain engineering
constraints and cannot be overridden by personal style.

Read this only when preparing concrete execution, reconciling an existing run,
or answering an explicit setup/capability/troubleshooting request. The Study owner
can execute a small action directly. For substantial vendor-specific work, use an
available native Codex subagent with a fresh context (`fork_turns="none"` where
supported). Do not forward the discussion transcript or all domain manuals.
If delegation or backend access is unavailable, the owner uses the same bounded
procedure directly and reports the limitation; no second agent framework is needed.

## Task brief

Provide only the information needed for the assigned action:

- Mode: execute, inspect/reconcile, or setup/probe; domain and exact desired outcome.
- Absolute repository/Study paths, experiment ref and fixed input/proposal/mapping
  refs; asset paths/versions and the relevant hypotheses and decision rule.
- Proposed realization, units, fixed conditions, allowed changes, required
  observations/quality checks and acceptance criteria. State any unresolved input.
- Selected backend and secure configuration location, working/output directory,
  resource/time bounds, and existing Run/task ids or idempotency keys.
- Ownership: which model/session, artifacts and record changes this executor owns;
  what is read-only; required result location. The agent is not alone in the workspace
  and must preserve other agents' changes.
- File lifecycle: the task's `output/<case-or-task>/` (or explicit external workspace),
  scratch subdirectory, retained deliverables/evidence and cleanup owner. Use the
  same separation in the selected remote workspace. Return artifact paths and
  dependencies before cleanup; follow the shared Study completion rules, including
  preserving referenced native outputs and reconciling unfinished runs first.

For setup/probe there may be no experiment yet: record the question and do only the
authorized discovery. Missing capabilities return a bounded finding, not invented
tools or an unsolicited model change. Do not pass credential values in the brief.

For a design imported from a product baseline, retain its fixed source product
identity, baseline reference, content hash and `asset_context`. Check that pinned
baseline's attachments before a new execution; review stale-source statements and
task-relevant gaps. Resolve external source roots explicitly after a move. Do not
replace a task's input with the latest product revision implicitly.

## Owner and execution boundaries

The Study owner chooses hypotheses, comparisons, acceptance criteria and next
experiments. The executor chooses implementation details within the brief; it must
not silently change physics, units, inputs, tolerances or decision rules to make a
run pass. Return a material mismatch or required scope change for the owner to
resolve; routine authorized actions do not need another user approval.

Assign one mutation owner to each shared desktop/model/session. Parallel CAD/CAE
work needs independent resources and satisfied dependencies. Transfer ownership
only after the prior executor stops and actual run state is reconciled. This is an
orchestration rule, not a distributed lock supplied by EDS. When a child can access
the Study, designate it to write only its Run/realization/evidence; otherwise the
owner journals those before/after dispatch. Do not submit if pre-call Run intent
cannot be durably recorded. Assessments and next-experiment decisions stay with
the Study owner; do not create duplicate Runs for the same remote action.

## Route the selected implementation

1. Discover the existing Codex/MCP binding and target tool first. Use
   `python -m eds execution <cad|cae> --backend <binding.json> --tools <tool-names.json> --capability <capability>`
   when a local binding check is useful. This checks the selected task's recorded
   tool inventory, not the whole domain or source/patch installation. It is not
   proof of a live service or valid geometry. A healthy binding routes directly to
   runtime task references. Source/patch checks belong to explicit maintenance.
2. When a source/configuration problem is observed, switch to
   [setup/troubleshooting](execution-setup.md); do not equate missing context
   with a need to reinstall.
3. For a healthy remote service, read [runtime execution](execution-runtime.md).
   It points to the selected upstream Skill's task-relevant capability/reference
   only; never load the complete root Skill or installation guide by default. If
   the selected source provides a general MCP but no applicable Skill, use its
   registered MCP documentation entry; do not relabel a specialized Skill as
   general. Record path/content hash and pinned commit. CAD drawings, 3D-to-2D
   annotation and BOM belong to the upstream CAD Skill; do not copy those
   implementations into EDS. Missing guidance remains a capability gap.
4. Check live MCP identity and the target tool's current schema before calling.
   Submodule presence, Skill loading, MCP connectivity and operation correctness
   are separate observations. Native host tools are preferred; use the existing
   official SDK helper only when needed. Keep service/schema evidence on disk.
5. Before mutation, use the Run section of `docs/record-format.md` to save the
   experiment, precise input snapshot and Run intent. Query already submitted,
   running or unknown work first, including after a timeout. If its identity cannot
   be recovered, report the gap without resubmitting or changing keys to bypass it.
   A completed observation explicitly bound as `read_only: true` may be repeated
   as a fresh Run. A confirmed unsent preflight failure may be retried after repair;
   retain its failed record. Neither case enables automatic retries.
   When choosing or repairing a route, query central feedback with
   `execution-guidance` or `failure-recovery`. Read the fixed version and
   compare conditions before changing the brief; reuse one selected guidance
   snapshot for the current Run instead of searching for every tool call.
   The default `resume` shows task identities and state without raw output. Use
   `show --run <run-id>` to inspect the assigned Run's exact inputs and history;
   do not load the whole Study to recover one task.
6. Execute within the brief. Preserve original outputs, task ids and artifacts;
   read back the actual model state that affects the question. Record realization
   differences and Evidence against exact input versions. Tool completion does not
   mean engineering acceptance. Use a quality reference/calculator only for a named
   check; do not load an entire optional methodology package for every operation.

## Compact return to the Study owner

Return a short result with these fields; files hold the full supporting detail:

- **Identity/status:** experiment/input refs, Run/task ids, completed/failed/unknown
  state, whether a remote action was sent, and how to reconcile unfinished work.
- **Actual state:** realized model/version and material differences from the brief.
- **Observations:** requested quantities with units and the numerical/geometry
  quality checks that affect interpretation; distinguish missing from zero.
- **Evidence:** exact record/artifact paths or URIs, versions/hashes and useful
  locators. Preserve relevant warnings and errors, not just a success label.
- **Decision needed:** remaining uncertainty, capability gaps or proposed scope
  change. Suggestions are not an already-selected next experiment.

Do not return complete tool lists, schemas, manuals or routine logs. The owner can
request a specific evidence slice or an independent check if interpretation needs
it. Compression must retain failed checks, unknown status and model differences.
Write the Assessment after this review and publish the iteration projection to
the bound central knowledge root. Publication preserves Run status and never
upgrades an unknown or failed operation into a successful engineering conclusion.
Write the Assessment after this review; begin the next iteration from the updated
Study summary instead of replaying the execution transcript.
