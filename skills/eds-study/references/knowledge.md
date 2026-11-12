# Knowledge retrieval by purpose

Read this when history can change the current decision. Use only a user-selected
knowledge workspace: logical collections share the Markdown registry and SQLite
index. Do not scan other directories or load every collection at startup.

When the portable data root is enabled, use `"@knowledge"` instead of repeating a
machine-specific path. `data use <root>` binds a copied root on a new computer;
`kb "@knowledge" sync` or `rebuild` performs only a local Markdown-to-SQLite
rebuild. Markdown units and the registry are portable truth, while SQLite,
locks and cache are local/rebuildable. Existing explicit paths remain supported.
The optional GraphQLite projection follows the same boundary: `graph.sqlite3` is a
local derived cache, rebuilt with `graph-sync`, and is never the source record or
a multi-machine merge artifact.

## Choose the question before searching

The current question takes priority over the stage. A stage is a fallback when the
question is not yet specific. These are retrieval routes, not evidence rankings:

| Question (`--question`) | First collection | Related collection when useful |
| --- | --- | --- |
| `design` | `design`: function, structure and tradeoffs | `feedback`: prior failures and limits |
| `method-selection` | `method`: mechanism and assumptions | `feedback`: tested applicability |
| `experiment-design` | `experiment`: controls, observations and decision rule | `method`: required assumptions |
| `result-interpretation` | `feedback`: actual conditions and discrepancies | `method`: explanations to distinguish |
| `cad-modeling` | `design` | scoped `preference`, relevant `feedback` |
| `drawing` | scoped `preference` | `design`, relevant `feedback` |
| `delivery` | scoped `preference` | `feedback`, `design` |
| `execution-guidance` | `feedback` | `method`, `design`, scoped `preference` |
| `failure-recovery` | `feedback` | `method`, `design` |

Method-selection, experiment-design and result-interpretation use the same
central feedback history. A method evaluation may have literature Evidence and
an Assessment before any Run exists. Keep literature claim, Codex inference and
runtime observation separate; a paper discussion cannot be labelled as a
verified product improvement until a suitable experiment exists.

`--stage` accepts `discussion`, `planning`, `execution`, `interpretation`, or
`delivery`. Do not use a stage to override a more specific question. Use `--domain`
and `--project` when applicable, and `--user`/`--team` only for the actual identity.
An explicit `--type` selects a collection for a deliberate follow-up. Missing
identity is not permission to search every person's preferences.

During execution planning or route changes, `execution-guidance` and
`failure-recovery` search central iteration feedback. Read the fixed version and
compare conditions before changing the brief; reuse one selected guidance
snapshot for the current Run instead of searching again for every tool call.
The result is a conditional candidate route or method applicability judgment. The Codex owner records adopted,
limited or rejected use and the actual outcome; a lexical match never directly
changes an MCP call.

```powershell
python -m eds kb <knowledge-root> route --question method-selection --stage planning
python -m eds kb <knowledge-root> search "辐射 边界条件" --question method-selection --domain cae --limit 5
python -m eds kb <knowledge-root> search "标注 尺寸" --question drawing --domain cad --user <user-id> --limit 5
```

Distinguish not-enabled, unavailable, no-match and matched. No match does not
automatically widen to every collection or project. Reformulate the engineering
question or deliberately query a related collection, recording material use.
The legacy unscoped search remains available for an intentional library search;
it is not the default research route. Current evidence can be sufficient without
a history search.

Normal search checks registered-source freshness; sync after source edits. A
fixed-version read validates the selected source and need not wait for unrelated
edits to be indexed. Use `kb <knowledge-root> status` for an explicit full index
audit when maintaining or troubleshooting the library, not before every query.

## Optional relationship graph

Keep SQLite/FTS5 as the default retrieval path. Install GraphQLite only when a task
needs bounded relationship, condition, or method-effect paths; see the repository
guide `docs/graph-knowledge.md`. Maintain it explicitly
with `graph-sync` or `sync/rebuild --graph`, and inspect it with `graph-status`.
`graph-search` seeds from the existing lexical index and returns fixed unit
references that must still be read and source-verified through the normal path.
Bound traversal to depth 0–3 and a finite node budget. Do not expose arbitrary
Cypher or write preferences into the engineering graph. If the optional extension
is missing or its cache is stale, report the graph route as unavailable and
continue with ordinary lexical search when that route is sufficient. `graph-status`
is diagnostic and reports these states; `graph-sync` creates or repairs the cache
with a usable optional runtime, while `graph-search` requires a fresh cache.

Do not perform graph lookup on every CAD/CAE tool call. Select one graph result set
for the current question or Run, record the fixed references and conditions used,
and reuse that snapshot through the execution. Preferences remain governed by the
activity preset mechanism; they are deliberately excluded from the engineering
graph.

## Select, read, then expand

Search returns candidate identities, brief matches and source/condition locators.
Read selected fixed versions before treating a lexical hit as applicable evidence:

```powershell
python -m eds kb <knowledge-root> read <unit-id> --version <version>
python -m eds kb <knowledge-root> read <unit-id> --version <version> --relation tested_by --depth 1 --max-units 5
```

Default `read` returns the selected unit in full and related-unit locators. It does
not recursively read related bodies. Prefer a separate fixed-id read for one
needed relation; use explicit depth/relation selection for a bounded group.
Depth is limited to 0–3 and the unit budget to 1–100 (default 20). Missing, cyclic
and unexpanded references remain visible. A filtered or bounded view does not
prove that all relevant evidence was reviewed.

Keep equations, symbols, units, assumptions and conditions together in the selected
unit. Read required dependencies before using an incomplete method. A `tested_by`
link is a lead to a result, not a statement that the result passed. Read contrary
or limiting evidence when it affects the decision.

## Record use or curate knowledge

### Cross-domain transfer and context budget

Keep a complete Study provenance graph separate from the curated knowledge graph.
An execution endpoint needs an outcome and source record; it does not automatically
deserve a reusable method unit. Do not publish every tool call as a general lesson.

Before retrieval, identify the current question, physical domain, regime, material
assumptions and validation goal. Search process methods separately from physical
methods and product results. Shared process methods (controlled comparisons,
verification gates, provenance and display semantics) may use `domain: engineering`;
physical methods should use a specific domain such as `thermal-fluid`. `domain`
is an exact metadata filter, not an ontology or an automatic applicability model.
Legacy `cae` records need explicit condition review before reuse.

For a new domain, first select at most three relevant method candidates. Read fixed
versions at depth 0, then assess applicability. A thermal-fluid result is not a
magnetic or wear-model validation. Transfer an experimental procedure only after
redefining its observables, equations and decision rule for the new physical domain;
do not transfer material values, error tolerances, operating budgets or performance
gains simply because the words "simulation" or "optimization" match.

Use graph traversal to answer a specific provenance or applicability question,
normally one hop and only the needed relation. It must not automatically expand
neighbor bodies into the active context. A zero-match result is valid and does not
justify broadening to unrelated physical domains. Record rejected cross-domain
candidates as well as adopted/limited ones. These are owner-enforced retrieval
rules; the current lexical index and graph do not implement a semantic firewall.

Compare historical conditions and evidence with the current task; record adopted,
limited or rejected use with a reason, unit/version, affected Study refs and actual
outcome. Source claims, observations and Codex interpretation remain distinct.
Do not copy entire units into the Study resume summary.

Only when creating or revising units, read [unit contracts](knowledge-units.md).
Only when managing/applying personal or team conventions, read
[engineering preferences](preferences.md). Preference extraction settings
`once/auto/later/skip` are separate from engineering preferences. Basic Study/Run/
Evidence/Assessment records remain mandatory regardless of optional extraction.
Every material iteration is also retained in central feedback; extraction
settings only control additional high-level curation.
