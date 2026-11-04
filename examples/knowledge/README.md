# Engineering knowledge workspace examples

These are **synthetic fixtures**, not solved or measured engineering results.
`synthetic-source.md` is a readable, cross-section source packet. It is source
material, not a knowledge unit: do not register it. Register only the method,
experiment and feedback Markdown files. Their references intentionally form
cycles, exercising bounded relationship traversal.

The unit format starts with exactly one HTML comment containing JSON:

```text
<!-- eds-knowledge: {"id":"stable-id","version":"1","type":"method","title":"Title","date":"2026-11-02","attribution":"author_claim","sources":[{"uri":"source.md","locator":"§ B, equation 1"}],"conditions":{"units":"SI"},"relations":[{"type":"uses","id":"other-unit","version":"1"}]} -->
```

`id`, `version`, `type`, `title`, `sources`, `conditions` and `relations` are
required. Identity/type/title and relation/source values must be nonempty text.
Unavailable sources are explicitly represented by `sources: []` together with
`sources_missing: true`; missing `date` or `attribution` produces read warnings.
`date`, `attribution`, `domain`, and `project` are strings when supplied.
Do not put credentials in sources. Paths to original material are references;
the index does not fetch external URLs or invent missing material.

Keep formulas, symbol definitions, units, assumptions, variables, controls,
observations and decision criteria in a complete unit. Useful optional named
fields include `problem`, `method`, `assumptions`, `experiment`, `feedback` and
`limitations`; arbitrary metadata fields are searchable. Distinguish author
claims, user observations and Codex inference in attribution or the body.
Register later semantic revisions as new `version` values and separate files
when an older version is still cited; source hashes additionally detect edits.

## Commands from the repository root

Copy this directory to a separate knowledge workspace, including its source
packet. For example, using `workspaces/knowledge-demo` as that copy:

```text
python -m eds kb workspaces/knowledge-demo register method-fluid-gap.md
python -m eds kb workspaces/knowledge-demo register experiment-gap-sweep.md
python -m eds kb workspaces/knowledge-demo register feedback-gap-laminar.md
python -m eds kb workspaces/knowledge-demo search "层流 pressure"
python -m eds kb workspaces/knowledge-demo read method-fluid-gap --version 1
python -m eds kb workspaces/knowledge-demo status
python -m eds kb workspaces/knowledge-demo sync
python -m eds kb workspaces/knowledge-demo rebuild
```

Construction/status is read-only and does not create a nonexistent workspace.
The first write creates `registry.json`; only its listed Markdown is indexed.
Registration validates all available documents before modifying the registry.
Successful registration separately reports `saved`, `registered`, and `indexed`.
If indexing fails after valid registration, the error says the document remains
saved and registered; `status` must be checked before treating it as searchable.

`sync` transactionally updates only changed units and removes outdated FTS and
relation rows; unchanged units retain their row IDs, and an unchanged sync does
not rewrite SQLite. Deleted files remain in the registry as explicit gaps but
are removed from active search. After sync, `consistent: true` means the index
matches available registered documents; `complete: false` still reports missing
registered source files. Search and read return that gap status. Search checks
registered file sizes and modification times; edits require sync before searching.
A fixed-id read checks the returned Markdown and can proceed while an unrelated
file awaits sync. Selected source changes never silently return an old citation.

`rebuild` atomically replaces only the derived index. It can recover a missing,
corrupt or unsupported-version SQLite database without re-extracting Markdown.
Explicit `status`, `sync` and `rebuild` audits verify more than SQLite page integrity: cached identities, full
content and metadata must agree with the source snapshot; every searchable field,
its encoded lexemes, and every versioned relation must agree with the complete
unit. Missing, extra, duplicate or inconsistent derived rows mark the audited index
unavailable. `sync` rebuilds these damaged caches. Normal reads verify selected
source content and metadata but do not audit every FTS or relation row; use
`status` if derived-index damage is suspected. These checks detect cache damage, not authenticated
or tamper-proof archival evidence; the registered Markdown remains authoritative.
An unsuccessful rebuild preserves the old database; if the source has changed,
that old database is stale and cannot be queried as current. OS-owned writer
locks automatically release after process exit; the lock file itself can remain.

Search uses SQLite FTS5 with English/Greek words and encoded Chinese bigrams;
single-character Chinese queries have character tokens. Lexical matching is not
engineering applicability. Use `--question method-selection` (or another question
route) before searching; `--stage` is a fallback. An explicit `--type` selects a
collection deliberately. Existing unscoped searches remain supported.

Search returns compact candidates and locators; `read` returns the complete
selected unit, including conditions, with related-unit locators. Related bodies
are not automatically loaded. Use `--relation tested_by --depth 1 --max-units 5`
to expand a selected relation, or read its exact id/version. Allowed depth is 0–3
and unit budget 1–100, default 20. Missing, cyclic and unexpanded identities remain
visible; `dependencies_complete: false` is not a failed engineering calculation.
Multiple versions require `--version`; missing targets never silently resolve to
a newer version.

The logical collections are `design`, `method`, `experiment`, `feedback`, and
`preference`. Legacy custom types are still readable. Category-specific curation
rules are in [unit contracts](../../skills/eds-study/references/knowledge-units.md).
The illustrative [drawing preference](preference-drawing-example.md) is optional
and is not a preference of the current user. Register it only in a fixture copy,
then query `--question drawing --user example-user`; no other identity should
receive it. Candidate and retired preferences require an explicit review filter.
