# Experiment model retention

Use this policy for agent-generated CAD/CAE experiment models in the assigned
local or remote workspace. Preserve user originals and explicit retention overrides.
The Study owner owns the keep/delete decision; the execution owner implements the
bounded manifest using the selected backend. This is a workflow obligation, not a
background janitor or a new automatic deletion capability in the record engine.

## Plan and checkpoint

- Before model-producing execution, record the owned roots, final artifact roles,
  cleanup owner, available disk space and an estimated peak allowance for the next
  solve, checkpoint and export. Include this policy in the execution brief.
- Recheck space before large saves/exports, after accepted iteration checkpoints,
  and at experiment completion. Once a successor is verified and no dependent or
  active Run needs its predecessor, clean superseded models promptly. Do not wait
  until the entire Study ends. If space is insufficient, clear eligible intermediates
  first; if still insufficient, report the shortfall before starting the large write.
- Keep one final model per distinct physical scheme and required use. Final startup
  and steady results, mesh/order verification, independent crosschecks and meaningful
  failed/geometry-only endpoints may each require a model. Explain each retained
  role; do not count every solver retry, continuation point or render copy as a scheme.
  Final means the selected endpoint with its original validity status, not the
  highest version number or latest modification time. Preserve external dependencies.
- Keep current recovery/checkpoint inputs while runs are active or unknown. Reconcile
  their actual state before removal. Live solver preferences/recovery directories,
  shared configuration and unrelated tasks are excluded; an old directory date does
  not prove that its contents are inactive. Do not force-close a solver for cleanup.

## Preserve history, remove redundant model binaries

Preserve fixed experiment/input identities, hypotheses, parameter/material/solver
settings, Run status (including failed/unknown), logs, quantitative metrics, quality
checks, assessments, selected field evidence/media and scripts needed to interpret
and reproduce the work. Keep graph node IDs, edges and their original meanings.
Do not delete a Run, evidence node or graph relationship to hide a missing model.
Retain a unique raw failure/field artifact when the preserved observations are not
enough to support the recorded conclusion. A historical reference alone does not
require retaining every superseded native model binary indefinitely.

Before deletion, write a manifest outside the deletion set. For each file include
its absolute location, size/mtime, scheme and role, relevant fixed record/graph refs,
reason and retained successor (if any). Include a known hash or verify one when
claiming content equality or a recoverable backup. Record local/remote copies and
dependencies explicitly. Do not silently relocate all intermediate models into a
different backup/cache directory merely to satisfy cleanup.

Append a lifecycle Evidence/decision linked to the affected records and manifest;
keep the historical records immutable. After execution, record per-file receipts,
timestamp and availability: retained, removed, archived at a verified location, or
deferred with a reason. These are manifest dispositions, not new Run statuses.
If an intermediate has no verified surviving copy, say that exact file restoration
is unavailable and recomputation may be necessary. Do not label it archived.

Later retrieval must follow the lifecycle disposition before loading an old model
path. Use preserved metrics/records for historical reasoning; resolve a retained
final model or verified archive only when appropriate to the requested experiment.
Do not substitute a newer model for a fixed historical input implicitly. If a graph
projection is rebuilt, retain the original experiment/evidence nodes and provenance
edges and include the lifecycle link; do not mark a removed artifact as available.

## Execute and verify

Resolve each allowlisted file under the owned absolute roots, reject path escapes
and reparse/symlink traversal, and check it is unchanged and not in use immediately
before removal. Delete exact intermediate files, not whole date/output directories.
Skip changed, locked, uncertain or out-of-scope files and record why. A superseded
file explicitly covered by this retention policy needs no repeated approval; a
user original, unique required evidence or scope expansion needs separate resolution.

Verify that retained models and dependencies still exist unchanged, the intended
files are gone, records/graph identities remain intact, and measured free space has
increased. Report actual freed bytes, remaining space, retained model roles and
deferred items. File-presence/hash checks do not establish solver acceptance; do
not claim models were reopened or recomputed unless that validation actually ran.
