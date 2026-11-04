# EDS-Agent domain method reference

This is an on-demand reference for a specific methodological gap. Read only the matching section; it is not startup material for every Study. It provides engineering decision criteria, not a fixed workflow menu and not a claim of physical validity.

## Shared vocabulary

- **Design** changes the object: function, structure, geometry/topology, material, interfaces, or parameters.
- **Model Proposal** changes the expression or physical interpretation: idealization, equations, assumptions, boundary representation, coupling, or intended use.
- **Realization** is what the configured backend actually created. Always record its key state and differences from the proposal.
- **Experiment** states the question, competing hypotheses, fixed conditions, changed variables, observations, comparison rule, and expected decision before execution.
- **Evidence** is an observed operation, backend state, numerical output, measurement, or located source. **Assessment** is the later interpretation and uncertainty.

## Candidate quality

Candidates are materially different when their structural logic, physical mechanism, idealization, or coupling changes the expected observation. Merely changing precision, mesh size, tolerance, or a scalar parameter is an experiment condition unless it changes the hypothesis. Every candidate needs intended use, applicability conditions, expected difference, and a falsifying or discriminating observation.

## CAD observations

Inspect units, topology validity, feature/reference stability, interfaces, material metadata, key dimensions, and the behaviour relevant to the design goal. Saving/exporting is an operation result; it does not establish design adequacy. Use documented design rules, direct measurements, geometry/kinematic checks, or trusted analytical relations as evaluation evidence.

## CAE observations

Inspect realized equations and domains, material laws, loads, constraints, interfaces, units, discretization, solver state, warnings, convergence/residuals, balance or conservation checks, and sensitivity. Mesh or time-step refinement supports numerical quality; it cannot by itself validate an incorrect physical hypothesis. Predictive claims require measurement, analytical/benchmark/reference evidence matched to the intended use.

### Static cantilever self-check (illustrative reference)

For a prismatic, slender, linearly elastic cantilever of length `L`, constant second moment `I`, Young's modulus `E`, and an end force `P`, an independent Euler--Bernoulli self-check gives tip deflection `delta = P L^3 / (3 E I)` and fixed-end bending stress `sigma = P L c / I`, where `c` is the outer-fibre distance. This is an analytical check, not an external validation source. It assumes small deflection, elastic isotropic material, slender-beam kinematics, and a load/resultant matching the idealization.

For a rectangular section `b x h`, `I = b h^3 / 12` and `c = h/2`. A short/deep beam or 3-D solid can show shear deformation and local load-introduction effects omitted by Euler--Bernoulli. A Timoshenko-style comparison adds a shear term approximately `P L/(kappa G A)` to tip displacement (`G` shear modulus, `A` area, `kappa` shear correction); coefficient and load details must be recorded, not guessed. Mesh refinement and residual checks test numerical error; agreement with the beam relation tests consistency with the idealization. Neither proves a real component physically predictive.

For a CAE experiment, record geometry/material/units, load and constraint realization, element type, mesh sizes, solver warnings, convergence or balance evidence, and the comparison region. Changing mesh density alone is a numerical-quality experiment; comparing slender and shear-sensitive models is a physical-idealization experiment.

## CAD change-behaviour experiment

Freeze the scenario and measurement procedure, vary one design decision with a predicted change, and compare key dimensions, topology/reference stability, mass/volume, clearances, or documented kinematic behaviour. A valid observation includes realized model version and units. Save/export success is only an operation observation. If a revision invalidates a face/edge reference or analysis mapping, record dependent objects and require regeneration or an explicit reuse assessment.

## Coupling observations

The mapping must answer: which design version maps to which analysis entities; what simplification or transformation was applied; which materials, units, interfaces, loads, and scenarios carry across; which changes invalidate inputs; and when a previous result remains applicable. A changed design can require geometry regeneration, remeshing, re-solving, or only a documented reuse decision depending on the mapping evidence.

## Units and uncertainty

Record units with every quantity and convert explicitly at boundaries. Keep tolerances, numerical settings, and physical assumptions distinct. Missing conditions remain missing; do not fill them with plausible values silently. A result may be useful for comparison while still insufficient for manufacturing release or physical validation.

## Knowledge use

When history can change the decision, choose the question route described in
`skills/eds-study/references/knowledge.md`: design, method selection, experiment
design, result interpretation, modeling, drawing or delivery. The explicit
question takes priority over stage. Search selected types and applicable scopes;
read complete selected units, then only necessary related versions and sources.
Compare conditions and record adopted, limited or rejected use. Lexical retrieval
is a lead, not evidence. Preserve author claims, observations and inferences
separately; scoped engineering preferences are conventions, not validation.
