---
name: graphify-semantics
description: "Use right after `/graphify`, or whenever the user wants to rename / clean up / add meaningful or semantic names to a knowledge graph — generic `Community N` clusters, vague connection labels (`references`/`uses`/INFERRED), or cryptic node labels — and refresh `GRAPH_REPORT.md` + the Obsidian wiki so `graphify-out` and the vault are easy to query. Naming is done in-agent by Claude, never Ollama/Gemini."
trigger: /graphify-semantics
---

# /graphify-semantics

A finishing pass that runs **after** `/graphify`. graphify builds the graph; this skill makes it *legible*: every leftover `Community N` gets a real 2–5 word name, vague edges (`references`, `uses`, INFERRED) get precise predicates, cryptic node labels get cleaned — then the report and the **Obsidian wiki** are regenerated so both `graphify-out/` and your vault are easy to query.

It **relabels only** — it never re-extracts and never re-clusters.

> **Default scope is ONE project.** Run it in (or point it at) a single repo's `graphify-out/`. Multi-repo and vault-mirroring are *optional* sections at the end — this skill never scans your whole drive.

## When to use

- Right after a `/graphify` build, to finish the labeling graphify leaves incomplete.
- When the user says: "rename the nodes/connections", "give the graph meaningful names", "clean up the communities", "semantic names for the graph", "make graphify-out / the vault easier to query".

## Hard rules (do not violate)

1. **Name in-agent. You (Claude) do the naming.** Read each cluster's membership and write the name yourself. **Never** offload to `graphify label --backend ollama`, Gemini, or any external model — even if a local Ollama is running. Subagents you dispatch are still *you*; they may not call external models either.
2. **Never re-cluster.** No `graphify cluster` / `cluster-only` / `update` as part of this skill. Community ids are stable identifiers; re-clustering shifts them and breaks every label. We only rename.
3. **Honest audit trail.** `apply` preserves the original relation (`original_relation`, `relation_source: claude-semantic`) and the original node label (`original_label` + searchable alias). Leave structural edges (`calls`, `imports`, `method`, `inherits`, `contains`, `rationale_for`) alone — they are already faithful.
4. **Idempotent.** Re-running only touches items still generic. Safe to repeat.
5. **`wiki`, never `obsidian`, into a vault.** The vault-facing export is **`wiki`** (one note per community). **Never** mirror the `obsidian/` export into a vault — it is one markdown file *per node* (thousands of files). `regenerate` always (re)builds `wiki`; it only refreshes `obsidian/` if you already had one, and never creates it.
6. **Mirror the report + `wiki/` only.** When copying into a notes vault, take `GRAPH_REPORT.md` (or a renamed copy) and `wiki/` — **never** raw-`/MIR` the whole `graphify-out` (that drags in `graph.json`, `cache/`, `obsidian/`, backups and scratch, and can purge hand-maintained notes).

## Environment quick reference

- **Interpreter (Windows):** the engine is stdlib-only for `plan`/`apply`/`status`/`merge`, but `regenerate` needs `graphify` importable. On most boxes that is **`C:\Python313\python.exe`** — a bare `python` is often missing or can't import graphify. Resolve once and reuse:
  ```powershell
  $SR = "$env:USERPROFILE\.claude\skills\graphify-semantics\scripts\semantic_rename.py"
  $T  = "<project-or-graphify-out path>"      # default: ./graphify-out
  $PY = (& C:\Python313\python.exe $SR resolve-python $T | Select-Object -First 1)
  ```
  `resolve-python` probes `sys.executable`, PATH `python`/`python3`, `C:\Python313`, and the uv-tool venv, then caches the winner in `.graphify_python`. (`regenerate` reuses the same probing, so it works even without a cached marker.)
- **Engine subcommands:** `resolve-python · plan · apply · regenerate · status · revert · merge`.
- **`graphify export` runs from the PROJECT ROOT** (the parent of `graphify-out`), not from inside `graphify-out`: `& $PY -m graphify export wiki`. Formats: `wiki` (use this) · `html` · `obsidian` (avoid for vaults).

## The pipeline (one project)

`plan → name (you) → apply → regenerate → verify`. Path defaults to `./graphify-out`.

### 1 — Plan
```powershell
& $PY $SR plan $T            # add --nodes to also flag cryptic node labels
```
Writes `graphify-out/naming_tasks.json` and prints:
```
communities needing names : N
connections to upgrade     : M (capped at 300/run)
cryptic nodes flagged      : K
communities total/named    : T/named
```
If nothing needs naming, say so and stop.

### 2 — Name it yourself (the core step)
Read `naming_tasks.json` (three lists) and write `graphify-out/names.json`. Only include items you can genuinely improve; omit the rest.

```json
{
  "communities": { "40": "Test Harness Suite", "104": "Toolbar Icon Assets" },
  "relations":   { "125": "returns", "212": "depends_on" },
  "nodes":       { "device": "Compute Device" }
}
```
Keys are the `community_id` / `link_index` / `node_id` from `naming_tasks.json`. (Duplicate community names are fine to write — `apply` auto-dedups them so wiki filenames stay unique — but prefer distinct names where you can.)

**Communities** — a 2–5 word Title Case name capturing what the cluster *is*. Let **`file_types` pick the style**:
- *code-heavy* → name by what the code does: `["SAM2UNet.py","dora_adapters.py"]` → `SAM2-UNet Training`; `["app.py","encode_image()"]` → `Image Cleaning App`.
- *paper / document-heavy* → name by the **subject** of the papers/citations: `Root Architecture Literature`, `Batch Normalization (Ioffe 2015)`.
- *rationale* → design-rationale notes: `Backbone Choice Rationale`.

Avoid generic words (Utilities, Misc, Module, Helpers). Reuse domain vocabulary already in the labels so `graphify query` matches.

**Connections** — one lowercase snake_case predicate for how `source` acts on `target`. Controlled vocabulary:
`configures · validates · persists · renders · schedules · transforms · serializes · depends_on · derived_from · returns · raises · emits · subscribes_to · documents · cites · supersedes · trains · evaluates · loads · saves · wraps · invokes · imports · references`
- `cuda_ok() —references→ bool` → `returns`
- `Trainer —uses→ SAM2UNet` → `trains`; `Trainer —uses→ FullDataset` → `loads`
- `DashApp —uses→ DataCache` → `depends_on`; `README —references→ install.sh` → `documents`

**Omit (leave graphify's original) when no precise predicate fits** — especially when the *source is a primitive type* (`int —uses→ X`) or the edge is an **input parameter** rather than a return. The static extractor can't distinguish return-vs-parameter, so don't force `returns` on every `fn → type` edge.

**Nodes** (`--nodes` only) — rename only genuinely cryptic labels (`cfg`, `device`, hashes, single letters). **Keep** real symbol names and real type names (`int`, `str`, `Tensor`). Skip anything already clear.

### 3 — Apply
```powershell
& $PY $SR apply $T           # reads names.json; auto-dedups colliding community names
```
Updates `graph.json` + `.graphify_labels.json`, writes the reversible audit `.graphify_semantic_map.json`, and backs up (`*.prelabel.bak`) first. Reports `disambiguated N colliding community name(s)` when it had to suffix a duplicate.

### 4 — Regenerate
```powershell
& $PY $SR regenerate $T
```
Rebuilds `GRAPH_REPORT.md` (reusing the existing clustering — never re-clustered) and **always (re)exports `wiki`** so the renamed labels actually reach Obsidian. `html`/`obsidian` are refreshed only if already present. Wiki note filenames, `[[wikilinks]]`, `community/…` tags, and `## Connections` predicates all update to match.

### 5 — Connection cap & residuals (don't chase zero)
`plan` surfaces at most 300 connections per run. To drain more, loop `plan → name → apply` — **but stop when a round makes no progress**, not when the count hits 0:
```
loop (max ~4 rounds):
  plan
  if "communities needing names" == 0 AND "connections to upgrade" == 0  → break
  if the counts did not drop since the previous round                    → break
  name the remainder → apply
```
**Expected residuals are normal, not failure:** empty `__init__.py` / `conftest.py` singletons, primitive-type clusters, and real type-name nodes (`int`, `str`, `device`) re-appear in every `plan` because you correctly omit them. Don't invent names to force a zero.

### 6 — Verify (don't claim done without this)
- `GRAPH_REPORT.md` community headers show real names, not `Community N`.
- `wiki/` exists and its note count > 0.
- No stray `Community_N.md` notes beyond the expected residuals above.
- If you mirrored to a vault: the vault report is refreshed (not stale) and there is **no `obsidian/` folder** in the vault.
- `& $PY $SR status $T` for the final named/upgraded counts.

## Large single graph (hundreds of communities)

When `naming_tasks.json` has too many items for one pass, chunk and fan out — still **one project**:

1. Split the `communities` list into chunks (and put relations/nodes in their own chunk).
2. Dispatch **general-purpose subagents**, one per chunk. Each is *you* naming in-agent (no Ollama/Gemini); each **writes a `names_part_<X>.json`** — a flat `{id: name}` community map, or the full `{communities, relations, nodes}` shape — and does **not** run `apply` (so they never race on `graph.json`).
3. Merge → dedup → single apply:
   ```powershell
   & $PY $SR merge $T --clean   # combine names_part_*.json -> names.json (deduped); remove scratch
   & $PY $SR apply $T
   & $PY $SR regenerate $T
   ```

## Optional — multiple repos

Run the per-project pipeline **in each repo the user explicitly names** (optionally one subagent per repo, in parallel). **Do not scan whole drives** for `graphify-out` folders — operate only on the repos you were pointed at.

## Optional — mirror into an Obsidian / notes vault

If you keep a vault, copy **only** `GRAPH_REPORT.md` (optionally renamed to `<project>.md` with your own frontmatter) **and `wiki/`** into the vault's project folder. Refresh the report; mirror `wiki/` *with purge* so renamed notes replace the old `Community_N.md` ones. **Never** copy the whole `graphify-out`, **never** copy `obsidian/`, and **never** purge hand-maintained index/Home notes. (If you have a sync script, check it doesn't `/MIR` the raw folder and doesn't skip drives your repos live on.)

## Common mistakes

| Mistake | Result | Do instead |
| --- | --- | --- |
| Trust `regenerate` to create a wiki | Pre-0.2 it only rebuilt *existing* formats → no wiki, names never reach the vault | 0.2 always exports `wiki`; on older engines run `graphify export wiki` yourself |
| Write duplicate community names | Wiki filename collision → notes overwritten | `apply`/`merge` auto-dedup; still prefer distinct names |
| `robocopy /MIR graphify-out → vault` | Drags `graph.json`/`cache`/`obsidian/`; purges hand notes | Mirror report + `wiki/` only |
| Mirror the `obsidian/` export | One file *per node* (thousands) floods the vault | Use `wiki/` |
| Loop until the count is 0 | Infinite loop on un-nameable boilerplate | Break on no-progress; accept residuals |
| Force `returns` on every `fn → type` edge | Mislabels input-parameter edges | Omit when source is primitive / edge is a parameter |
| Scan `D:\*\graphify-out` to "do everything" | Touches repos the user didn't ask about | Per project; only the repos you're given |

## Red flags — STOP

- About to run `graphify cluster` / `update` "to refresh" → that re-clusters; don't.
- About to call Ollama / Gemini / `graphify label` "to save time" → naming must be in-agent.
- About to `/MIR` `graphify-out` into the vault, or copy `obsidian/` → wrong; report + `wiki/` only.
- Claiming done without checking `wiki/` exists and the report shows real names → verify first.

## Undo

```powershell
& $PY $SR revert $T          # restores graph.json + labels from *.prelabel.bak
& $PY $SR regenerate $T      # rebuild outputs from the restored state
```

## CLI

`resolve-python · plan [--nodes] [--no-relations] [--max-relations N] [--max-nodes N] [--force] · apply [--names FILE] · regenerate · status · revert · merge [--clean]`. Path defaults to `./graphify-out`.

## Querying after a rename

graphify's `query` matches on node/community **labels** (case-folded substring + IDF — no synonyms). Real names like `Mask Tracing UI` and precise predicates like `depends_on` mean `graphify query "how does mask tracing work"` hits the named community instead of missing `Community 40`, and Obsidian Graph View reads like a real second brain.

## Optional: auto-run after /graphify

Skills don't auto-chain. To link them, add one line at the end of `~/.claude/skills/graphify/SKILL.md`: *"After the build completes, invoke `/graphify-semantics` on the same path to finish community/connection naming."* Or just invoke it yourself after a build.
