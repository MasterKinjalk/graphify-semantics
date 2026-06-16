# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] - 2026-06-15

A reliability pass driven by a real multi-repo run that exposed silent failures.

### Fixed
- **`regenerate` now always (re)builds the `wiki` export** instead of only rebuilding
  formats the project already had. Previously a project with no prior wiki got renamed
  labels that never reached Obsidian — the single biggest silent failure.
- **`apply` auto-deduplicates community names** before they become wiki filenames, so
  identical sibling-cluster names no longer collide and silently overwrite each other
  (collisions get a ` (<cid>)` suffix).
- **`regenerate`'s interpreter probing** now matches `resolve-python` (adds `C:\Python313`
  and the uv-tool venv), so regeneration works without a pre-set `.graphify_python` marker.

### Added
- **`merge` subcommand** — combines `names_part_*.json` (from chunked large-graph naming)
  into one deduped `names.json`; `--clean` also removes scratch files (`names_part_*`,
  `chunk_*`, `_dump_*`).
- Expanded connection vocabulary (`trains`, `evaluates`, `loads`, `saves`, `wraps`,
  `invokes`, `imports`, …) and explicit guidance to omit a predicate when the source is a
  primitive type or the edge is an input parameter (not a return).
- A verification checklist and an "expected residuals" note (empty `__init__`/`conftest`
  singletons, type-name nodes) so a non-zero remaining count isn't mistaken for failure.

### Changed
- **Per-project is now the documented default.** Removed the "scan `D:\*\graphify-out` /
  `F:\*\graphify-out`" framing from the README and walkthrough; multi-repo and vault
  mirroring are optional and never scan whole drives.
- **Vault-mirror guidance**: copy `GRAPH_REPORT.md` + `wiki/` only — never raw-`/MIR` the
  whole `graphify-out`, never the per-node `obsidian/` export.

## [0.1.0] - 2026-06-15

Initial release.

### Added
- `graphify-semantics` Claude skill (`SKILL.md`) — a labeling pass that runs after `/graphify`.
- `scripts/semantic_rename.py` engine with subcommands: `resolve-python`, `plan`, `apply`, `regenerate`, `status`, `revert`.
- In-agent community naming for generic `Community N` clusters (never offloaded to external models).
- Connection-label upgrades for vague/`INFERRED` edges, preserving `original_relation` and tagging `relation_source`.
- Optional cryptic node-label cleanup (`--nodes`) with searchable aliases.
- Report + `wiki`/`obsidian`/`html` regeneration that reuses existing clustering (never re-clusters), with a text-substitution fallback.
- Reversible audit map (`.graphify_semantic_map.json`) and pre-label backups.
- README, MIT license, and an annotated example walkthrough.
