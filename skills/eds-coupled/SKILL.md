---
name: eds-coupled
description: "Reason about CAD/CAE correspondence, cross-domain evidence and experiment iterations in one engineering Study."
---

# Coupled design and analysis reasoning

Use one Study and `eds-study` continuity rules. Start with this method alone; load
`eds-cad` or `eds-cae` only if the current decision needs that domain's additional
criteria. A coupled topic does not require both software execution manuals.

Relate each design version to its analysis expression: entities, idealization,
materials, units, interfaces, loads/scenario and transformations. State which
changes invalidate the relation or dependent results and what permits reuse.
Exchanging a file alone does not establish this correspondence.

Identify whether the current question concerns design, physical interpretation or
their mapping. When the starting expression is inadequate, develop materially
different candidates and a discriminating observation. Record the next experiment's
fixed conditions, affected versions, measurements and decision rule before dispatch.
Only operate the affected end when the mapping supports that choice.

For an execution step, the selected execution owner follows
[execution handoff](../eds-study/references/execution.md). Keep CAD and CAE services
independently verified, and serialize work that shares a desktop or model. A gap at
one end does not discard valid work at the other.

Interpret the returned design/analysis states and mapping differences together.
Separate geometric success, numerical quality and engineering meaning. Decide
whether evidence calls for a design revision, a physical hypothesis change, a
mapping repair or another observation. Read only the needed coupling section of
repository-root `docs/methods.md` if these criteria are insufficient.

Use the shared knowledge route for the current question rather than querying all
CAD/CAE collections. Expand only the method, experiment or feedback relations that
affect the correspondence or reuse decision; preserve their fixed versions.
