# Setup and troubleshooting route

Read only the branch matching the observed failure. Installation, transport,
credentials and compatibility are separate problems; do not load all branches
or reinstall by default.

1. **Not discovered:** check the existing Codex/MCP configuration and local
   binding locations first. Report `not_found` versus `not_configured`; only
   after confirming no usable source exists should installation be considered.
2. **Missing execution source:** inspect the pinned submodule and its manifest;
   apply only the repository-owned patch set required by that source. Keep the
   patch report separate from runtime tool/schema evidence.
3. **Transport or reachability failure:** inspect the selected endpoint, route,
   service listener and relevant transport diagnostics. Do not reinstall a
   healthy source because a remote service is unreachable.
4. **Authentication failure:** use the existing credential/configuration
   location and report its state without exposing secret values. Do not replace
   credentials or write global settings from this route unless explicitly asked.
5. **Version or capability mismatch:** compare the observed source/tool/schema
   with the pinned requirement and read only the matching compatibility patch or
   task reference. A mismatch is not proof that every patch is applicable.

Read repository-root `docs/execution-skills.md` for confirmed source installation
or patch maintenance, and only the relevant section of `docs/backend-integration.md`
for binding/transport setup. For SolidWorks local environment setup, use upstream
`SKILL.md` environment/self-check sections and `references/troubleshooting.md`.
For COMSOL setup, select the applicable `Install` / `Codex Configuration` section
of `MCP/COMSOL/README.md`; Java build/fallback instructions apply only to that chosen
runtime. These are conditional pointers, not additional startup reads.

A capability can be genuinely unsupported. Report that gap instead of attempting
installation or applying an unrelated patch. Local source verification does not
verify what a remote process loaded; retain that deployment uncertainty explicitly.

Use `python -m eds execution <cad|cae> --backend <binding.json> --tools
<tool-names.json> --maintenance --full` for detailed checks of the selected local
source and patch set. Ordinary checks do not replay patches or inspect other
backends; `--full` changes the output detail, not the scope of checking. Neither
mode claims a live connection, remote deployment identity or engineering validity.
