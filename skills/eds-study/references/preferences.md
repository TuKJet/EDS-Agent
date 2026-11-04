# Scoped engineering preferences

Read for a relevant modeling, drawing or delivery convention, or when the user
asks to manage preferences. These units are separate from extraction settings and
from methods/experimental evidence. They do not override explicit current task
requirements, applicable engineering standards or verified physical constraints.

## Capture only what was established

Use `type: preference` and the common [unit metadata](knowledge-units.md). Additional
required fields are:

- `preference_key`: one stable subject, such as `drawing.dimension_style`.
- `value`: the specific convention, as nonempty text.
- `scope`: `user`, `team`, or `project`; `scope_id`: the corresponding identity.
- `preference_status`: `candidate`, `confirmed`, or `retired`.
- `origin`: `explicit` or `inferred`.

An inferred habit is a candidate; it cannot be confirmed without an explicit user
statement or confirmation. One task-specific choice stays in that task unless the
user expressed a reusable preference. Do not repeatedly ask about already explicit
preferences. Record the source locator and applicability, including the relevant
process (3D modeling, 2D annotation, delivery) and project restrictions.
For a convention specific to one activity, set optional `question` to the shared
route such as `cad-modeling`, `drawing` or `delivery`; retrieval then excludes it
from other explicit questions. Optional `stage` applies when routing by stage
without a specific question. Omit these only for a genuinely general convention.

```json
{"id":"drawing-dim-style","version":"1","type":"preference","title":"Drawing dimension convention","domain":"cad","sources":[{"uri":"preferences-source.md","locator":"User statement dated 2026-11-04"}],"conditions":{"process":"2d-drawing"},"relations":[],"preference_key":"drawing.dimension_style","value":"Example convention explicitly chosen by the user","scope":"user","scope_id":"example-user","preference_status":"confirmed","origin":"explicit"}
```

This is an illustrative schema, not a preference of the current user.

## Retrieval and conflicts

Normal search returns only confirmed preferences whose scope matches the supplied
`--user`, `--team` or `--project`. Do not invent an identity to obtain matches.
An optional unit `project` restriction further limits a personal/team preference.
Use `--preference-status candidate` or `retired` only for an explicit review;
candidates and retired entries are not automatically applied.

Different scopes can coexist. Check the current project requirements and whether
a general convention applies. When matching confirmed records disagree on the
same subject, preserve the conflict and read the cited records; do not silently
choose the highest lexical score. A deliberate correction creates a new version
and a `supersedes` relation; keep the earlier source/version for historical work.
Retirement and confirmation are explicit Markdown revisions followed by sync or
registration, not a second hidden preference store.
Only an explicit confirmed/retired revision with the same subject, scope and
applicability can supersede a prior preference. A candidate or a narrower project
exception cannot silently retire a general convention. Conflicts remain visible
within the search limit through bounded `conflict_refs`; read those versions.

Scoped search is retrieval hygiene, not filesystem access control. An explicit
fixed-id read can inspect a selected unit, including candidates for review.
Knowledge that requires access isolation belongs in separately authorized roots.
