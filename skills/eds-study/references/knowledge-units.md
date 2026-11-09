# Knowledge unit curation

Read only when registering, extracting or revising reusable knowledge. Preserve
original sources and raw engineering outputs outside distributable Skills. Each
unit answers one reusable question and retains sufficient conditions to interpret
it; a paper chapter or chat turn is not automatically a knowledge unit.

## Collection contracts

| `type` | Required engineering meaning in the body | What must remain separate |
| --- | --- | --- |
| `design` | Function, constraints/interfaces, alternatives, chosen tradeoff and rejected options with reasons | A design idea is not proof of strength or manufacturability |
| `method` | Problem, mechanism, assumptions, equations with symbol/unit definitions, required inputs, applicability and limits | Source authors' claims versus our interpretation and validation |
| `experiment` | Question, method versions, variables, fixed conditions, controls, observables, comparison rule and budget | Planned setup versus what was actually executed |
| `feedback` | Actual experiment/Run versions, realized conditions, quality checks, observations, uncertainty, failures and applicability | Solver success, numerical quality and engineering adequacy |
| `preference` | Specific convention, owner/scope, explicit source and status | Personal choice versus technical requirements; see [preferences](preferences.md) |

Project iterations are published into the central personal knowledge root as
versioned `feedback` projections. This is a provenance rule, not a new logical
collection: the Study remains the source record, while the projection keeps
conditions, route, expected-versus-actual observations, failure/repair,
validation and reuse outcome. Future retrieval, n-gram/PLE or small-model
exports can therefore be added without rewriting every Study.

Method evaluations are equally valuable to tool-execution feedback. Preserve
the paper or method versions, product feature and operating conditions, parameter
change, baseline/candidate metrics, and one of `improved`, `degraded`, `no_change`
or `unverified`. A literature-only assessment remains unverified for the product;
it may guide a candidate experiment but cannot become a verified improvement.

When one source contains several kinds of knowledge, create linked units rather
than putting every kind into one summary. Link a method to its experiment and
feedback by fixed versions. Preserve negative and inconclusive outcomes. The
current task's original records are not replaced by reusable knowledge extraction.
An iteration projection is created after an Assessment, including failed and
inconclusive iterations. Pending or unknown Runs remain inconclusive and cannot
be promoted to verified success.

## Markdown and provenance

Register only explicitly selected Markdown files. One metadata comment supplies
`id`, `version`, `type`, `title`, `sources`, `conditions`, and `relations`:

```markdown
<!-- eds-knowledge: {"id":"thermal-radiation-method","version":"1","type":"method","title":"Radiative loss model","domain":"cae","date":"2026-11-04","attribution":"author_claim","sources":[{"uri":"paper.pdf","locator":"p.4 eq.2"}],"conditions":{"regime":"source-defined"},"relations":[]} -->
# Radiative loss model
## Problem, mechanism and assumptions
## Equations, symbols and units
## Applicability, limitations and source claims
```

Use actual data instead of the illustrative placeholders. Each source requires
`uri` and `locator`. A genuinely missing source is explicit (`sources: []`,
`sources_missing: true`), never invented. Such a unit is a limited lead, not
independent substantiation. Dates and attribution should be present; missing values
remain visible warnings. `domain` and `project` are optional exact filters.

The body distinguishes **author-claim**, **user-observation** and
**codex-inference**, including uncertainty. Multi-source claims retain their own
locators. Relations use stable id/version pairs: `uses`, `tested_by`, `supports`,
`limits`, `contradicts`, `supersedes`, or `derived_from`. Relations are not automatic
instructions to load other bodies. Changed meaning, evidence or applicability
creates an explicit revision; do not overwrite cited historical versions.

For iteration feedback, preserve observed facts, Codex interpretation and
reusable guidance as separate parts. A repair suggestion without a supporting
validation reference remains unverified; a source or hash alone does not prove
engineering adequacy.

Legacy method/experiment/feedback and custom-type units remain readable. The
tool validates the common metadata and the preference-specific contract; Codex
must check the category-specific engineering meaning above. A structurally valid
record alone does not certify its contents.

## Extraction and lifecycle

`once` records a requested extraction then returns to `later`; `auto` uses configured
stage boundaries; `later` keeps records for future extraction; `skip` omits extra
extraction. Later extraction can use only preserved sources. Repeated extraction
reuses the same unit/version or records an explicit revision.

Report saved Markdown, registered documents, current indexed hashes, stale files,
broken references and pending extraction separately. Register/sync after saving;
an extraction event alone does not prove searchability. SQLite is derived and can
be rebuilt from registered Markdown without model calls. Explicit `status`,
`sync` and `rebuild` perform full derived-index checks; routine retrieval verifies
freshness and the selected source without repeating that maintenance audit.
