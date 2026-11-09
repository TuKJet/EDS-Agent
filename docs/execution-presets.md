# Activity presets for repeated execution

Activity presets keep repeated CAD and drawing runs on a stable style snapshot.
They reuse the existing scoped `preference` units; they are not a new memory
database and never modify a public Skill.

## Context and files

The context must identify the work independently of a person’s prose request.
Use a domain and question plus at least one of `user`, `team` or `project`:

```json
{
  "domain": "cad",
  "question": "drawing",
  "user": "example-user",
  "project": "example-project"
}
```

The knowledge root is a user-selected knowledge workspace containing registered
preference units. It must not be a public Skill directory. The first activation
requires an explicit `--refs` JSON file, even for a neutral empty preset:

```json
[]
```

## Lifecycle

Activate a named preset with explicit fixed `id`/`version` references. The
references must be confirmed, applicable to the context, and not superseded.
Activation validates and stores a compact snapshot. Later activation of the same
name without `--refs` reuses the fixed stored version; it does not search the
knowledge index. If a knowledge unit is edited externally, the active preset does
not change silently. Activate again with new references to adopt the revision.
The activation owner checks the selected units' engineering applicability once.
Known process/preset restrictions are checked locally; arbitrary engineering
conditions are retained in the snapshot for the owner, not interpreted by a new
rule engine. Explicit question routing takes priority over fallback stage routing,
as in the existing knowledge contract.

```text
python -m eds preset <knowledge-root> activate my-drawing --context context.json --refs refs.json
python -m eds preset <knowledge-root> activate my-drawing --context context.json
```

`current` reads the active snapshot for the exact context. `task` creates a task
snapshot whose `base` is the complete fixed preset, whose `overrides` are only
the current task's temporary values, and whose `values` are the effective values.
The task snapshot includes a revision/hash summary. It is the input for every
part in a batch, so an old batch remains unchanged when a later default changes.

```json
{
  "drawing.dimension_density": "medium",
  "delivery.export_format": "png"
}
```

```text
python -m eds preset <knowledge-root> current --context context.json
python -m eds preset <knowledge-root> task --context context.json --overrides overrides.json --output task.json
```

Task overrides do not write a preference. `save-default` is the explicit action
for a reusable change. Its `--source` must state the durable source of the
request (for example, an explicit user instruction or project convention), and
its default scope is `user`. Only changed fields create new confirmed explicit
preference revisions through the existing preference mechanism; an identical
value is a no-op. A team or project default must use that scope deliberately and
must not rewrite a team/project source as a user preference.
Defaults are specific to the named preset. Replacing an imported general convention
creates a narrower `derived_from` preference; it does not retire that general
convention. Later revisions within the same preset use `supersedes`. Manual history
searches may show both; inspect their applicability instead of taking lexical rank
as a precedence rule.

```text
python -m eds preset <knowledge-root> save-default --context context.json --overrides overrides.json --source "explicit user request for future drawing tasks"
```

The normal execution path is `current`/`task` snapshot consumption. It performs
no n-gram search, no knowledge read, and no preference write. The execution owner
maps effective values to fields supported by the selected vendor `DrawingSpec`
and reports applied or unmapped settings. A snapshot does not imply that every
vendor supports every style option, and this workflow alone is not SolidWorks or
VM acceptance evidence.

Attach the fixed task snapshot to each Run in the batch:

```text
python -m eds study <study-root> run --data run.json --preset-task task.json
```

The Run input stores and validates the snapshot without knowledge access. This
records intended settings; the execution owner still records how they mapped to
actual vendor parameters and what the resulting drawing demonstrated.

## Conversation behavior

Codex interprets the request; these commands remain deterministic record tools.
An ordinary request uses the selected preset without a confirmation dialog. A
"this time" change becomes a task override. An explicit "from now on" request
updates only the relevant default fields and needs no second confirmation.
An ambiguous correction stays task-local; do not infer a lasting preference from
acceptance of a drawing. Show the active preset briefly when the context changes,
not before every part. These are conversation conventions, not new desktop UI
buttons or a second model loop.

If saving fails, source files may have been prepared or registered while the
active preset remains unchanged. The error identifies this state. Retrying the
same values and source reconciles it without adding duplicate revisions. The
registry/index and active selection are recoverable writes, not one database
transaction. Preset selection is not filesystem access control.
