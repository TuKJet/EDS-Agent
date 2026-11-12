# Product takeover reference

Read this reference only for a task that creates, resumes, updates, validates,
binds or publishes an existing product baseline. It is a routing contract, not a
vendor CAD/CAE manual.

## Route

1. Resolve the private EDS root and product identity (`@product/<id>` or an explicit
   product root). Keep the product separate from public Skills.
2. Read the compact product view, then select a fixed `product-baseline@N`; do not
   edit from an unpinned or newer source file.
3. Ask only for task-relevant gaps. Start with drawings and explicit text, then add
   CAD/BOM/CAE/document assets when available. Do not require an exhaustive form or
   approval gate. The user can provide files and natural-language notes; Codex
   produces the narrow JSON payload for the CLI and asks only task-blocking
   questions.
4. Distinguish observed/document/user-report/inference. Preserve locators and hashes;
   preserve original wording in raw text attachments; use gaps for conflicts and
   unknowns. Never fabricate historical experiments.
5. Freeze the baseline before binding an existing Study or choosing a new CAD/CAE
   task. Load [execution handoff](execution.md) and the selected upstream execution Skill
   only if actual asset readback or backend execution is required.

## CLI contract

The product command accepts a root path or `@product/<id>`:

```text
product <root-or-@product/id> init --product-id <safe-id> --name <text>
product <root-or-@product/id> resume
product <root-or-@product/id> show [--ref product-baseline@N]
product <root-or-@product/id> attach <file> --asset-id <safe-id>
  --role drawing|cad|bom|cae|document|text|other
  --base product-baseline@N [--revision vendor-revision]
product <root-or-@product/id> update --data JSON --base product-baseline@N
product <root-or-@product/id> check-assets [--ref product-baseline@N]
product <root-or-@product/id> use --study <existing @study/task>
  --baseline product-baseline@N
product <root-or-@product/id> publish --baseline product-baseline@N
  [--knowledge-root path]
```

`init` creates empty `product-baseline@1`. Each attach/update creates a new
revision. `@product/id` resolves `studies/products/id` in the existing personal
root; no new manifest format is introduced. `use` binds an existing Study and does
not rewrite its historical record. Repeating `use` with the same source baseline is
idempotent. Explicitly using a newer baseline of the same product appends a new
design revision in the target Study; prior designs and Runs stay pinned to their old
version. There is no automatic latest-following behavior.

## Statement contract

The update JSON may contain optional `name`, `statements` and `gaps`. Statements
upsert by `id` and contain:

```json
{
  "id": "overall-length",
  "subject": "housing",
  "topic": "envelope",
  "text": "Overall length is 120 mm.",
  "attribution": "document",
  "sources": [{"asset_id": "drawing-r1", "locator": "sheet 1, view A"}],
  "value": 120,
  "unit": "mm",
  "validation": "unverified"
}
```

`attribution` is `document`, `user` or `codex`. A source is `{uri, locator}` or
`{asset_id, locator}`. `value`/`unit` are optional. Validation defaults to
`unverified`; `verified` additionally requires explicit `verification_sources`
(`{uri, locator}`) separate from the statement's original `sources`. This checks
provenance, not engineering correctness, and must not be used merely because Codex
inferred a value. Explicit raw `.txt`/`.md` attachments use role
`text` and retain their text locator. Gaps replace the prior gaps only when the
field is supplied; use them for conflicts and missing information. Product
constraints and preferences remain separate records.

## Example handoff

For a drawing plus user text, pin both source revisions, record the drawing's shown
dimensions and the user's stated intent with separate attribution, and leave unknown
material as a gap. Then freeze the baseline and create or bind CAD and CAE Studies
against that exact reference. A 2D-only takeover remains partial: it does not prove
an absent 3D feature tree, CAE setup, or engineering acceptance.

`check-assets` checks presence and hashes only. After a meaningful intake/completion
batch, `publish` writes central design Markdown and fixed JSON into the existing
knowledge registry/index and returns a fixed knowledge identity/version. Do not publish every chat
sentence or file action. `use` returns the target Study's internal design ref; include
that design ref in later Experiment/Run inputs for impact tracking, and keep the
published knowledge identity in external `knowledge_refs`. `use` never changes the target Study mode. Future Assessment feedback
remains in the existing central experience mechanism. No automatic OCR,
complete CAD parser, hidden design-intent reconstruction, model client, second agent
loop or engineering acceptance is implied. Readable PDF/text facts or selected
backend readback may be used when explicitly available; otherwise record the gap.

Replacing an asset ID pins a new file but keeps earlier statement sources intact.
`resume.stale_sources` and the `stale_source_statements` in task/publication snapshots
identify statements needing review before engineering reliance. `use` checks both
current attachments and retained historical statement attachments; missing or changed
files block reuse. `resume` and `publish` do not rehash every large attachment.
Bindings within the same managed root stay relative; external bindings carry explicit
source roots and `requires_rebind_on_move`. Native assembly dependencies must remain
available in a working copy; attachment registration does not rewrite CAD references.
