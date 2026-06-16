# Walkthrough: a real run

This is an annotated end-to-end run on a real graphify project — a computer-vision
codebase (`Root-Mask-and-Skeletons`) whose graph had **2,346 nodes, 3,846 edges,
and 180 communities**.

## 0. Starting state

After `/graphify` finished, `status` showed the gap:

```
$ python scripts/semantic_rename.py status D:\Root-Mask-and-Skeletons
graphify-out: D:\Root-Mask-and-Skeletons\graphify-out
  communities : 150/180 named (30 still generic)
  connections : 0 upgraded; 1448 still vague
```

30 clusters were still `Community N`; ~1,450 edges used a vague relation.

## 1. Plan

```
$ python scripts/semantic_rename.py plan D:\Root-Mask-and-Skeletons
PLAN written to ...\graphify-out\naming_tasks.json
  communities needing names : 30
  connections to upgrade     : 300 (capped)
  cryptic nodes flagged      : 0 (node pass off; use --nodes)
  communities total/named    : 180/150
```

`naming_tasks.json` contains the context Claude needs — for each community its
members, file-type mix, and source files:

```json
{
  "community_id": 40,
  "current_label": "Community 40",
  "size": 7,
  "file_types": { "code": 6, "rationale": 1 },
  "top_members": ["test_regression.py", "conftest.py", "test_area_calc()", "..."],
  "source_files": ["tests/test_regression.py", "tests/conftest.py"]
}
```

and, for each vague edge, the two endpoints and current relation:

```json
{ "link_index": 125, "current_relation": "references", "confidence": "EXTRACTED",
  "source_label": "cuda_ok()", "source_type": "code",
  "target_label": "bool", "target_type": "code" }
```

## 2. Claude names it (in-agent)

Claude reads `naming_tasks.json` and writes `names.json`. This is the only step
that requires judgement, and it is done by Claude itself:

```json
{
  "communities": {
    "40": "Test Harness Suite",
    "104": "Toolbar Icon Assets",
    "179": "ResNet Generator Internals"
  },
  "relations": {
    "125": "returns"
  }
}
```

## 3. Apply

```
$ python scripts/semantic_rename.py apply D:\Root-Mask-and-Skeletons
APPLIED: 3 community names, 1 relations, 0 node labels
  graph.json + .graphify_labels.json updated; audit -> .graphify_semantic_map.json
```

In `graph.json`, the upgraded edge keeps its history:

```json
{ "relation": "returns", "original_relation": "references",
  "relation_source": "claude-semantic", "confidence": "EXTRACTED" }
```

## 4. Regenerate

```
$ python scripts/semantic_rename.py regenerate D:\Root-Mask-and-Skeletons
REGENERATE: report=api; exports=['html', 'wiki']
```

`regenerate` always (re)builds the `wiki` export, so even a project that never had one gets
per-community notes with the new names. The report no longer mentions `Community 40`, and
the Obsidian wiki notes are renamed:

```
wiki/Test_Harness_Suite.md          (was Community_40.md)
wiki/Toolbar_Icon_Assets.md         (was Community_104.md)
wiki/ResNet_Generator_Internals.md  (was Community_179.md)
```

Every `[[wikilink]]`, `community/…` tag, and `## Connections` predicate that
pointed at those clusters is rewritten to match.

## 5. Mirror to your vault (optional)

Copy **only** the report + the per-community wiki into your vault's project folder — never
the whole `graphify-out`, and never the per-node `obsidian/` export:

```powershell
Copy-Item "D:\Root-Mask-and-Skeletons\graphify-out\GRAPH_REPORT.md" "$vault\Root-Mask-and-Skeletons.md"
robocopy "D:\Root-Mask-and-Skeletons\graphify-out\wiki" "$vault\Root-Mask-and-Skeletons\wiki" /MIR
```

Obsidian Graph View now shows named clusters and labeled connections.

## Re-running is safe

```
$ python scripts/semantic_rename.py plan D:\Root-Mask-and-Skeletons
  communities needing names : 27   # the 3 just named are skipped
```

The pass is idempotent — it only ever touches what's still generic — and fully
reversible with `revert`.

## Tidy every project at once

```bash
SR="$HOME/.claude/skills/graphify-semantics/scripts/semantic_rename.py"
for d in /d/*/graphify-out /f/*/graphify-out; do
  [ -f "$d/graph.json" ] || continue
  python "$SR" plan "$d"
  # name -> names.json, then:
  python "$SR" apply "$d" && python "$SR" regenerate "$d"
done
# then run sync-graphify-vault.ps1 once
```
