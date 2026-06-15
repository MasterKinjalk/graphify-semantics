---
name: graphify-semantics
description: "Semantic post-processor for /graphify. After a knowledge graph is built, Claude names every generic 'Community N' cluster and upgrades vague connection labels IN-AGENT (never Ollama/Gemini), rewrites cryptic node labels on request, then regenerates GRAPH_REPORT.md + the Obsidian wiki so the second brain is easy to query. Use right after /graphify, or whenever the user asks to rename / clean up / add meaningful or semantic names to graph nodes, communities, connections, the graphify-out folder, or the Obsidian vault."
trigger: /graphify-semantics
---

# /graphify-semantics

A finishing pass that runs **after** `/graphify`. graphify builds the graph; this skill makes it *legible*: every leftover `Community N` gets a real 2-5 word name, vague edges (`references`, `uses`, INFERRED) get precise predicates, and the report + Obsidian wiki are regenerated so both the `graphify-out/` folder and the vault are easy for Claude to query.

It does **not** rebuild or re-extract the graph. It only (re)labels what graphify already produced.

## When to use

- Immediately after a `/graphify` build, to finish the labeling graphify leaves incomplete.
- When the user says: "rename the nodes/connections", "give the graph meaningful names", "clean up the communities", "make graphify-out / the vault easier to query", "semantic names for the graph".
- As a periodic tidy-up across all projects under the vault.

## Hard rules (do not violate)

1. **Name in-agent. You (Claude) do the naming.** Read the community membership and write the names yourself. **Never** offload to `graphify label --backend ollama`, Gemini, or any external model, even if a local Ollama is running. The user explicitly wants session-level understanding driving the names.
2. **Never re-cluster.** Do not run `graphify cluster`, `--cluster-only`, or `--update` as part of this skill. Community ids are stable identifiers; re-clustering shifts them and breaks every hand label. We only rename.
3. **Keep the audit trail honest.** When upgrading a connection, the engine preserves the original relation as `original_relation` and tags it `relation_source: claude-semantic`. Leave structural edges (`calls`, `imports`, `method`, `inherits`, `contains`, `rationale_for`) alone — they are already faithful.
4. **Idempotent.** Re-running only touches items still generic. Safe to run repeatedly.

## Where the engine lives

```bash
SR="$HOME/.claude/skills/graphify-semantics/scripts/semantic_rename.py"
```

Run it against a project's `graphify-out/` (the authoritative copy lives in each source repo, e.g. `D:\<project>\graphify-out`; the vault is a mirror). If the user gives no path, default to `graphify-out` in the current directory.

---

## Step 0 - Resolve the Python interpreter

The engine itself is stdlib-only for `plan`/`apply`/`status`, but `regenerate` needs graphify importable. Resolve once (handles the known Windows quirks — `C:\Python313`, the uv-tool venv, empty `.graphify_python`):

```bash
TARGET="${1:-graphify-out}"          # project root or its graphify-out dir
PY=$(python "$SR" resolve-python "$TARGET" | head -1)
echo "Using interpreter: $PY"
```

`resolve-python` reuses a valid `.graphify_python`, else probes `python`, `C:\Python313\python.exe` (the RootQuant exception), and the uv-tool venv until one can `import graphify`. If `python` isn't even on PATH, run it as `C:\Python313\python.exe "$SR" resolve-python "$TARGET"`.

## Step 1 - Plan

```bash
"$PY" "$SR" plan "$TARGET" --nodes      # drop --nodes to skip node-label cleanup
```

This writes `graphify-out/naming_tasks.json` and prints a summary:

```
communities needing names : N
connections to upgrade     : M (capped at 300/run)
cryptic nodes flagged      : K
communities total/named    : T/named
```

If everything is already named, it says so — stop and tell the user there's nothing to do.

## Step 2 - Name it yourself (the core step)

**Read `graphify-out/naming_tasks.json`.** It has three lists, each with the context you need. Produce `graphify-out/names.json`. Only include items you can genuinely improve; omit the rest.

**Communities** — for each entry, look at `top_members`, `file_types`, and `source_files`. Write a **2-5 word Title Case** name that captures what the cluster *is*:

- members `["app.py","select_folder()","encode_image()","create_image_card()"]` → `"Image Cleaning App"`
- members `["SAM2UNet.py","dora_adapters.py","curriculum_scheduler.py"]` → `"SAM2-UNet Training"`

Avoid generic words ("Utilities", "Misc", "Module"). Prefer the domain vocabulary already in the labels so `graphify query` matches.

**Connections** — for each entry, pick **one lowercase snake_case predicate** describing how `source` acts on `target`, given their labels and `file_type`s. Use a precise verb from a small controlled vocabulary, e.g.:

`configures · validates · persists · renders · schedules · authenticates · transforms · serializes · depends_on · derived_from · returns · raises · emits · subscribes_to · documents · cites · supersedes`

- `cuda_ok() --references--> bool` → `returns`
- `DashApp --uses--> DataCache` → `depends_on`
- `README --references--> install.sh` → `documents`

If no precise predicate fits, omit it (leave graphify's original).

**Nodes** (only if `--nodes` was used) — rename only genuinely cryptic labels (`device`, `cfg`, hashes). Keep real symbol names. Skip anything already clear.

Write `names.json` exactly like:

```json
{
  "communities": { "40": "Test Harness Suite", "104": "Toolbar Icon Assets" },
  "relations":   { "125": "returns", "212": "depends_on" },
  "nodes":       { "device": "Compute Device" }
}
```

Keys are the `community_id` / `link_index` / `node_id` from `naming_tasks.json`.

**Large graphs:** if there are many communities/relations, work through `naming_tasks.json` in batches and merge into one `names.json` before applying. For very large jobs, dispatch a few **general-purpose subagents** (one per chunk of the lists) — but every subagent is *you* naming in-agent; none may call Ollama/Gemini.

## Step 3 - Apply

```bash
"$PY" "$SR" apply "$TARGET"             # reads graphify-out/names.json
```

Updates `graph.json` (relations + node labels, originals preserved) and `.graphify_labels.json` (complete community map), and writes a reversible `.graphify_semantic_map.json`. Backups (`*.prelabel.bak`) are made automatically.

## Step 4 - Regenerate outputs

```bash
"$PY" "$SR" regenerate "$TARGET"
```

Rebuilds `GRAPH_REPORT.md` (via graphify's own `report.generate`, reusing existing clustering — never re-clustered) and re-runs `graphify export` for whatever formats the project already had (`html`, `wiki`, `obsidian`). The community notes are renamed and every `[[wikilink]]`, `community/…` tag, and `## Connections` predicate is rewritten to match. A text-substitution fallback guarantees the report stays consistent even if the API path is unavailable.

## Step 5 - Mirror into the Obsidian vault

The authoritative artifacts are in the source `graphify-out/`; the vault is a robocopy mirror. Push the changes with the user's existing sync (PowerShell, run on the host — not the sandbox):

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\scripts\sync-graphify-vault.ps1"
```

If that script isn't present, mirror manually: `robocopy <src>\graphify-out <vault>\graphify\<project> /MIR /XD cache`.

## Step 6 - Report back

Run `status` and summarize for the user:

```bash
"$PY" "$SR" status "$TARGET"
```

Tell them: how many communities were named, how many connections upgraded, that the report + wiki + vault are refreshed, and that `/graphify query "…"` and Obsidian Graph View will now use the new names.

---

## Querying after a rename

This directly improves retrieval. graphify's `query` matches on node/community **labels** (case-folded substring + IDF — no synonyms). Real names like `"Mask Tracing UI"` and precise predicates like `depends_on` mean:

- `/graphify query "how does mask tracing work"` hits the named community instead of missing `Community 40`.
- `/graphify path "Dash App" "Data Cache"` traces an edge labeled `depends_on`, not `uses`.
- Obsidian Graph View clusters and connection labels read as a real second brain.

## Run across every project

```bash
for d in /d/*/graphify-out /f/*/graphify-out; do
  [ -f "$d/graph.json" ] || continue
  python "$SR" plan "$d" --nodes
  # name -> names.json, then:
  python "$SR" apply "$d" && python "$SR" regenerate "$d"
done
# then run sync-graphify-vault.ps1 once
```

## Undo

```bash
"$PY" "$SR" revert "$TARGET"     # restores graph.json + labels from *.prelabel.bak
"$PY" "$SR" regenerate "$TARGET" # rebuild outputs from the restored state
```

## Optional: make it run automatically after /graphify

You chose to keep this separate. If you ever want it to fire automatically, add one line at the very end of `~/.claude/skills/graphify/SKILL.md` (after its Step 8):

> After the build completes, invoke `/graphify-semantics` on the same path to finish community/connection naming.

Skills don't auto-chain on their own, so that pointer (or just invoking `/graphify-semantics` yourself after a build) is what links them.
