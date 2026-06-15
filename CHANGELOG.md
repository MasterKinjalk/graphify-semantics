# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
