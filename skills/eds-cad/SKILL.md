---
name: eds-cad
description: "Reason about CAD design alternatives, discriminating experiments and realized design behaviour, independently of a CAE backend."
---

# CAD design reasoning

Use the shared Study and `eds-study` continuity rules. This method is backend-neutral;
load no software operation guide merely to discuss a design or its results.

Translate the goal into function, interfaces, structure, material, units, constraints
and observable behaviour. Separate design choices from tolerances and execution
settings. When the current expression is inadequate, develop at least two materially
different candidates, their expected consequences and a distinguishing observation.

For the next experiment, specify the candidate/input versions, changed variable,
fixed scenario, measurements and decision rule. Interpret realized dimensions,
topology, interfaces and reference stability only as relevant to that question.
Saving or exporting a file does not establish design adequacy; use requirements,
direct measurements, documented design rules or trusted reference calculations.
A CAD-only study need not invent a CAE model.

For useful history, route by `design`, `cad-modeling`, or `drawing` in the shared
knowledge reference. Apply only confirmed preferences for the current user/team/
project; drawing style is not evidence of geometric or manufacturing adequacy.

Read the CAD sections of repository-root `docs/methods.md` only for a methodological
gap. When a concrete experiment is ready to run, its execution owner follows
[execution handoff](../eds-study/references/execution.md). Keep feature operations,
drawings/BOM procedures and MCP details in that execution context. Evaluate its
returned actual-state differences and evidence before deciding the next iteration.
