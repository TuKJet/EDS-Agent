# Portable personal data root

EDS can keep reusable knowledge, activity presets, Studies and selected
attachments under one portable directory. The default is `~/EDS-Data`; an
explicit root takes precedence, followed by `EDS_DATA_HOME`, the local binding
in `~/.eds/config.json`, and then the default.

Initialize or bind a root:

```powershell
python -m eds data init --user-id <stable-user-id>
python -m eds data init D:/private/EDS-Data --user-id <stable-user-id>
python -m eds data use D:/private/EDS-Data
python -m eds data status
```

The manifest records only the schema, stable identity, and relative
`knowledge/`, `studies/` and `assets/` directories. The portable truth is
Markdown and `registry.json`, `study.json`, preset state and deliberately
selected attachments. SQLite indexes, lock files, temporary files, credentials,
backend bindings and VM-specific absolute paths are local or rebuildable.
Each data directory includes `.gitkeep` so even initially empty directories
survive a private Git checkout.
The local binding is `~/.eds/config.json`; caches and process locks default to
`~/.eds/cache/` (override with `EDS_CACHE_HOME`, consistently for all processes
using the same root). Neither belongs in the synchronized data root. Atomic
writes briefly use adjacent `.tmp` files; exclude these from the sync tool.

Use aliases after binding a copied root:

```powershell
python -m eds kb "@knowledge" sync
python -m eds kb "@knowledge" rebuild
python -m eds preset "@knowledge" current --question drawing
python -m eds preset "@knowledge" task --question drawing --output batch/style-task.json
python -m eds study "@study/gearbox" resume
```

`sync` and `rebuild` are local Markdown-to-index operations. They are not remote
synchronization or conflict resolution. To move to another computer, synchronize
the whole root with a private Git repository or controlled file-sync tool, run
`data use <root>`, then run `kb "@knowledge" sync` or `rebuild`. Presets and Studies
then use the same relative layout. Put CAD/PDF/image attachments under `assets/`
to carry them with the root; old project absolute paths and large CAD files outside
the root are not migrated automatically and still need rebinding or deliberate
copying, followed by asset hash checks.

There is no automatic merge for two computers editing the same Study or
preference revision. Alternate use is the safe default; concurrent edits require
explicit review. The root is a portable source directory, not a remote service and
not a replacement for VM/MCP credentials or backend discovery.
