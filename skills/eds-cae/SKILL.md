---
name: eds-cae
description: "Formulate CAE physical hypotheses, discriminating experiments and result interpretations from an analysis object, without requiring editable upstream CAD."
---

# CAE physical reasoning

Use the shared Study and `eds-study` continuity rules. Work from the quantity of
interest, mechanism, domain, material laws, loads, boundary/initial conditions,
interfaces, units, assumptions and intended use. Keep solver operation guides out
of formulation, result discussion and iteration planning.

When uncertainty is substantive, compare at least two physical hypotheses or
idealizations with predicted differences and a discriminating observation. Numerical
settings are experiment conditions unless they change the physical hypothesis.
Specify numerical-quality observations and comparison rules before execution.

Keep the proposal separate from the realized model. Assess tool/solver completion,
numerical quality and physical adequacy separately. Convergence cannot validate an
incorrect hypothesis; predictive claims need applicable measurement, analytical,
benchmark or trusted reference evidence. Retain competing hypotheses if the data
do not distinguish them. A CAE-only study does not require an editable CAD model.

Read the matching CAE section of repository-root `docs/methods.md` only for a
specific methodological gap; analytical examples are not default startup material.
Load an optional quality reference only to answer a named issue such as convergence
or provenance, rather than adding another complete workflow. When an experiment
is ready, its execution owner follows [execution handoff](../eds-study/references/execution.md).
Use the compact returned observations, actual-state differences and evidence to
decide the next iteration; missing execution capability does not block formulation.

For useful history, use `method-selection`, `experiment-design`, or
`result-interpretation` in the shared knowledge reference. Keep source claims and
actual validation feedback separate; retrieve linked conditions before reusing a
result. Do not load CAD drawing preferences to discuss physical hypotheses.
