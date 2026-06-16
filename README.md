# graphify-semantics

> A semantic finishing pass for [graphify](https://pypi.org/project/graphifyy/) knowledge graphs — run by **Claude**, in-agent.

`graphify` turns a folder of code, docs, papers, and images into a navigable knowledge graph (communities, an honest audit trail, an Obsidian wiki, GraphRAG-ready JSON). But it routinely ships a graph that's only *half* legible:

- dozens of clusters are left named **`Community 40`**, **`Community 104`** … instead of something you'd actually search for;
- many edges are labeled with vague verbs — **`references`**, **`uses`**, **`related_to`** — that say nothing about *how* two things connect.

`graphify-semantics` is a Claude skill that finishes the job. It reads what graphify built and has **Claude name every generic cluster and upgrade every vague connection**, then regenerates the report and the Obsidian wiki so your second brain is actually queryable — by you in Obsidian, and by Claude via `graphify query`.

It is a **labeling pass, not a rebuild**: it never re-extracts and never re-clusters.

---

## Table of contents

- [The problem, concretely](#the-problem-concretely)
- [What it does](#what-it-does)
- [Why this makes a graph queryable](#why-this-makes-a-graph-queryable)
- [Install](#install)
- [Usage](#usage)
- [Use cases](#use-cases)
- [How it works](#how-it-works)
- [What gets changed (data model)](#what-gets-changed-data-model)
- [Design rules](#design-rules)
- [CLI reference](#cli-reference)
- [Requirements](#requirements)
- [Safety & reversibility](#safety--reversibility)
- [License](#license)

---

## The problem, concretely

A real graphify build of a computer-vision codebase produced **180 communities** — but **30 of them** were still named `Community N`, and **~1,450 of 3,846 edges** used a vague relation. In the Obsidian vault that surfaces as wiki notes literally titled `Community_104.md` and connection lines that read `[[X]] - \`references\` [EXTRACTED]`.

You can't query what you can't name. `graphify-semantics` closes that gap.

| Before | After |
| --- | --- |
| `Community 40` | `Test Harness Suite` |
| `Community 104` | `Toolbar Icon Assets` |
| `cuda_ok() —references→ bool` | `cuda_ok() —returns→ bool` |
| `DashApp —uses→ DataCache` | `DashApp —depends_on→ DataCache` |

---

## What it does

1. **Names every generic community** — reads each cluster's member nodes, file-type mix, and source files, then writes a 2–5 word Title Case name (`Mask Tracing UI`, `Training Pipeline`).
2. **Upgrades vague connections** — replaces fuzzy/`INFERRED` edges with a precise snake_case predicate (`configures`, `validates`, `persists`, `depends_on`, `returns`, `documents`, …), **preserving the original** so the audit trail stays honest. Structural edges (`calls`, `imports`, `method`, `inherits`, `contains`) are left untouched.
3. **Cleans cryptic node labels** *(optional, `--nodes`)* — renames things like `cfg`/`device` while keeping the old token as a searchable alias.
4. **Regenerates outputs** — rebuilds `GRAPH_REPORT.md` and **always (re)builds the `wiki` export** (per-community notes) so the renamed labels actually reach Obsidian; `html`/`obsidian` are refreshed only if the project already had them. Wiki note filenames, `[[wikilinks]]`, `community/…` tags, and connection labels all update consistently.
5. **Mirrors to your vault** *(optional)* — copy `GRAPH_REPORT.md` + `wiki/` into the vault's project folder. Never mirror the whole `graphify-out`, and never the per-node `obsidian/` export.

The naming is done **in-agent by Claude** — never offloaded to a small local model — so it uses session-level understanding of the codebase, not keyword guesses. Identical community names are auto-deduplicated so wiki filenames never collide.

## Why this makes a graph queryable

graphify's `query` matches on node and community **labels** (case-folded substring + IDF — no stemming, no synonyms). So the labels *are* the search index:

- `graphify query "how does mask tracing work"` now hits **`Mask Tracing UI`** instead of missing `Community 40`.
- `graphify path "Dash App" "Data Cache"` traces an edge labeled **`depends_on`**, not `uses`.
- Obsidian **Graph View** clusters and connection labels finally read like a second brain.

## Install

This is a [Claude skill](https://docs.claude.com/en/docs/claude-code/skills) (works with Claude Code and Cowork). Drop it in your skills folder:

```bash
git clone https://github.com/MasterKinjalk/graphify-semantics.git \
  ~/.claude/skills/graphify-semantics
```

Or copy the folder so the layout is:

```
~/.claude/skills/graphify-semantics/
├── SKILL.md
└── scripts/
    └── semantic_rename.py
```

That's it — Claude will pick up `/graphify-semantics` on the next session. The engine is **standard-library Python** for planning/applying; it only needs `graphify` importable for the regeneration step.

## Usage

Run it right after a `/graphify` build:

```
/graphify-semantics                       # operate on ./graphify-out
/graphify-semantics D:\my-project          # operate on a specific project
/graphify-semantics D:\my-project --nodes  # also clean cryptic node labels
```

Under the hood the skill orchestrates the engine in four moves — **plan → name → apply → regenerate** — where the *name* step is Claude itself:

```bash
SR="$HOME/.claude/skills/graphify-semantics/scripts/semantic_rename.py"
PY=$(python "$SR" resolve-python "$TARGET" | head -1)

python "$SR" plan "$TARGET"          # -> graphify-out/naming_tasks.json
# Claude reads naming_tasks.json and writes graphify-out/names.json
"$PY" "$SR" apply "$TARGET"          # update graph.json + labels + audit map
"$PY" "$SR" regenerate "$TARGET"     # rebuild report + wiki/obsidian/html
```

See [`examples/walkthrough.md`](examples/walkthrough.md) for a full annotated run.

## Use cases

**1 — Finish a fresh build.** You just ran `/graphify D:\my-service`. Half the communities are `Community N`. Run `/graphify-semantics D:\my-service` and every cluster gets a real name; the report and Obsidian wiki regenerate.

**2 — Make an Obsidian "second brain" navigable.** Your vault mirrors several `graphify-out` folders. After semantics, Obsidian Graph View shows named clusters and labeled connections instead of numbered blobs — you can actually wander it.

**3 — Improve Claude's retrieval over your code.** Because `graphify query` matches on labels, naming the graph measurably improves answer quality for "how does X work / what depends on Y / trace the data flow through Z."

**4 — Clean a big graph, or several repos.** For a graph with hundreds of communities, chunk the naming across general-purpose subagents (each writes a `names_part_*.json`) and combine with `merge`. Working across several repos? Run the per-project pass in each repo you choose (optionally one subagent per repo). It's idempotent, so re-running only touches what's still generic — and it never scans your whole drive.

**5 — Sharper relationships for GraphRAG / Neo4j.** Precise predicates (`configures`, `persists`, `depends_on`) make the exported `graph.json` / Cypher far more useful for downstream retrieval than a sea of `references`.

## How it works

```
/graphify build                  graphify-semantics
──────────────                   ──────────────────────────────────────────────
graph.json  ─┐
.graphify_labels.json ─┐
GRAPH_REPORT.md        │   plan ──▶ naming_tasks.json
wiki/ , obsidian/      │             (generic communities, vague edges, cryptic nodes
                       │              + member labels, file types, source files)
                       │                         │
                       │              Claude names them in-agent
                       │                         │
                       │                         ▼
                       └──▶ apply ──▶ names.json ▶ graph.json + .graphify_labels.json
                                                   + .graphify_semantic_map.json (audit)
                                                          │
                                       regenerate ◀───────┘
                                          │  report.generate (reusing existing clustering)
                                          │  graphify export wiki | obsidian | html
                                          ▼
                                   updated report + vault  ──▶ sync to Obsidian
```

The engine does all the mechanical work; Claude supplies only the judgement (the names). For very large graphs the skill can fan the naming out to general-purpose subagents — but every subagent is still *Claude* naming in-agent, never an external model.

## What gets changed (data model)

graphify's `graph.json` is a GraphRAG node-link document. The engine touches three things:

- **Community names** — `.graphify_labels.json` maps `community_id → name`. We fill in the generic ones. Community **ids never change** (so hand-labels never drift).
- **Connection labels** — each link's `relation`. When upgraded, the engine stores `original_relation` and tags the link `relation_source: "claude-semantic"`, leaving `confidence` intact.
- **Node labels** *(opt-in)* — a node's `label`, with `original_label` kept and the old value added to `aliases` so the literal query matcher still finds it.

Everything is recorded in `.graphify_semantic_map.json` for a clean revert.

## Design rules

These are enforced by the skill and the engine:

1. **Name in-agent.** Claude reads membership and writes the names. Never offloaded to Ollama/Gemini or any external backend.
2. **Never re-cluster.** No `cluster-only`/`update` as part of this skill — community ids are stable identifiers; re-clustering would shift them and break every label.
3. **Honest audit trail.** Vague/`INFERRED` edges are refined; faithful structural edges are left alone; originals are always preserved.
4. **Idempotent.** Re-running only processes items still generic.
5. **Reversible.** Pre-label backups (`*.prelabel.bak`) plus the audit map make `revert` a one-liner.
6. **`wiki`, not `obsidian`, for a vault.** Mirror `GRAPH_REPORT.md` + the per-community `wiki/` only — never the whole `graphify-out`, never the per-node `obsidian/` export.

## CLI reference

`scripts/semantic_rename.py` (run with any Python for plan/apply/status; needs `graphify` for `regenerate`):

| Subcommand | What it does |
| --- | --- |
| `resolve-python [path]` | Find a Python that can `import graphify` (probes `C:\Python313` + the uv venv); cache it in `.graphify_python`. |
| `plan [path] [--nodes] [--no-relations] [--max-relations N] [--max-nodes N] [--force]` | Detect generic communities, vague connections, cryptic nodes → `naming_tasks.json`. |
| `apply [path] [--names FILE]` | Apply Claude's `names.json` to `graph.json` + labels; **auto-dedupes community names**; write the audit map. |
| `regenerate [path]` | Rebuild `GRAPH_REPORT.md` + **always (re)export `wiki`** (refresh `html`/`obsidian` only if already present). |
| `status [path]` | Show how many communities are named and how many connections upgraded. |
| `merge [path] [--clean]` | Combine `names_part_*.json` (chunked naming) → deduped `names.json`; `--clean` removes scratch. |
| `revert [path]` | Restore `graph.json` + labels from the pre-label backups. |

`path` defaults to `./graphify-out`.

## Requirements

- A graph already built by [`graphify`](https://pypi.org/project/graphifyy/) (`graphify-out/graph.json` present).
- Python 3.9+ (the engine is stdlib-only for plan/apply/status; `regenerate` imports `graphify` + `networkx`).
- Claude Code or Cowork, to drive the naming step.

## Safety & reversibility

`apply` writes `graph.json.prelabel.bak` and `.graphify_labels.json.prelabel.bak` before changing anything. To undo:

```bash
python scripts/semantic_rename.py revert D:\my-project
python scripts/semantic_rename.py regenerate D:\my-project
```

The audit file `.graphify_semantic_map.json` records every old → new mapping (communities, relations, nodes).

## License

[MIT](LICENSE) © 2026 Kinjalk Parth

---

*graphify-semantics is an independent companion skill. `graphify` / `graphifyy` is a separate project; this repo only post-processes its output.*
