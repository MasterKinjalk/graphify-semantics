#!/usr/bin/env python3
"""
semantic_rename.py - the mechanical engine behind the `graphify-semantics` skill.

It does the deterministic work; *Claude* (the host agent) does the naming judgement.
Flow:  plan  ->  (Claude writes names.json)  ->  apply  ->  regenerate

Subcommands
-----------
  plan        Read graphify-out/graph.json, find generically-named communities,
              vague connections, and cryptic nodes. Emit naming_tasks.json with
              rich context for Claude, plus a human summary.
  apply       Read names.json (written by Claude) and apply it to graph.json +
              .graphify_labels.json. Writes a reversible audit map. Idempotent.
  regenerate  Rebuild GRAPH_REPORT.md + wiki/obsidian/html from the updated
              graph + labels (best effort; text-substitution fallback).
  status      Show how many communities/relations are still generic.
  merge       Merge names_part_*.json (chunked naming) -> names.json, deduped.
  revert      Undo the last apply using the audit map.
  resolve-python  Find a Python that can `import graphify`; write .graphify_python.

Design rules baked in (from the user's conventions):
  * NEVER re-cluster. Community ids are stable; we only (re)name them.
  * Naming is done in-agent by Claude, never offloaded to Ollama/Gemini.
  * Structural code edges (calls/imports/method/inherits/contains/...) are
    faithful and are left alone. Only vague/INFERRED edges are upgraded, and the
    original is preserved so the audit trail stays honest.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# A community label still counts as "generic" (needs a real name) if it matches:
GENERIC_COMMUNITY_RE = re.compile(r"^\s*community[\s_\-]*\d+\s*$", re.IGNORECASE)

# Relations that are vague enough to benefit from a precise predicate.
# Structural / already-meaningful relations are deliberately NOT in this set.
VAGUE_RELATIONS = {
    "references", "reference", "uses", "use", "related", "related_to",
    "relates_to", "connected", "connected_to", "link", "links", "linked",
    "mentions", "see_also", "associated_with", "conceptually_related_to",
    "semantically_similar_to", "similar_to", "", None,
}
# These are kept verbatim - they are precise and (usually) EXTRACTED.
STRUCTURAL_RELATIONS = {
    "contains", "calls", "imports", "imports_from", "method", "inherits",
    "re_exports", "rationale_for", "shares_data_with", "implements",
    "extends", "instantiates", "decorates", "returns", "raises",
}

GRAPH = "graph.json"
LABELS = ".graphify_labels.json"
AUDIT = ".graphify_semantic_map.json"
PYMARK = ".graphify_python"
DETECT = ".graphify_detect.json"


# --------------------------------------------------------------------------- #
# IO helpers
# --------------------------------------------------------------------------- #

def _read_json(p: Path, default=None):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"WARN: could not parse {p.name}: {e}", file=sys.stderr)
        return default


def _write_json(p: Path, data) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _out_dir(arg: str | None) -> Path:
    """Resolve the graphify-out directory from an argument or the CWD."""
    if arg:
        p = Path(arg)
        if p.name != "graphify-out" and (p / "graphify-out").is_dir():
            p = p / "graphify-out"
    else:
        p = Path("graphify-out")
    if not (p / GRAPH).exists():
        sys.exit(f"ERROR: no {GRAPH} found at {p}. Run /graphify first.")
    return p


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Graph helpers
# --------------------------------------------------------------------------- #

def _nodes(g):  # tolerate both 'nodes' and node-link shapes
    return g.get("nodes", [])


def _links(g):
    return g.get("links", g.get("edges", []))


def _by_community(g):
    out = defaultdict(list)
    for n in _nodes(g):
        out[n.get("community")].append(n)
    return out


def _id2node(g):
    return {n.get("id"): n for n in _nodes(g)}


def _degree(g):
    deg = Counter()
    for l in _links(g):
        deg[l.get("source")] += 1
        deg[l.get("target")] += 1
    return deg


def is_generic_community(label: str | None) -> bool:
    return label is None or label == "" or bool(GENERIC_COMMUNITY_RE.match(str(label)))


# --------------------------------------------------------------------------- #
# resolve-python
# --------------------------------------------------------------------------- #

def cmd_resolve_python(args) -> None:
    out = _out_dir(args.path)
    mark = out / PYMARK
    # 1. reuse an existing, *valid* marker
    if mark.exists():
        cand = mark.read_text(encoding="utf-8").strip()
        if cand and _imports_graphify(cand):
            print(cand)
            return
    # 2. probe candidates (shared with regenerate's _python_for)
    for c in _interpreter_candidates():
        if c and _imports_graphify(c):
            mark.write_text(c, encoding="utf-8")
            print(c)
            return
    # 3. give up gracefully - caller can still run plan/apply (stdlib only)
    fallback = sys.executable
    mark.write_text(fallback, encoding="utf-8")
    print(fallback)
    print("WARN: could not confirm `import graphify`; regenerate may be limited.",
          file=sys.stderr)


def _imports_graphify(py: str) -> bool:
    try:
        r = subprocess.run([py, "-c", "import graphify"],
                           capture_output=True, timeout=40)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _interpreter_candidates() -> list[str]:
    """Python interpreters to probe for `import graphify`, best-effort order.
    Shared by `resolve-python` and regenerate's `_python_for` so BOTH find the
    same interpreter - notably C:\\Python313 and the uv-tool venv on Windows,
    where a bare `python` is often absent or can't import graphify."""
    return [
        sys.executable,
        shutil.which("python"),
        shutil.which("python3"),
        r"C:\Python313\python.exe",
        os.path.expanduser(r"~\AppData\Roaming\uv\tools\graphifyy\Scripts\python.exe"),
    ]


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def cmd_plan(args) -> None:
    out = _out_dir(args.path)
    g = _read_json(out / GRAPH)
    labels = _read_json(out / LABELS, {}) or {}
    audit = _read_json(out / AUDIT, {}) or {}
    id2node = _id2node(g)
    deg = _degree(g)
    comms = _by_community(g)

    # ---- communities needing a name -------------------------------------- #
    done_comm = set((audit.get("communities") or {}).keys())
    comm_tasks = []
    for cid, members in sorted(comms.items(), key=lambda kv: -len(kv[1])):
        if cid is None:
            continue
        cur = labels.get(str(cid))
        if not is_generic_community(cur):
            continue                      # already has a real name
        if str(cid) in done_comm and not args.force:
            continue                      # already handled in a prior run
        members_sorted = sorted(members, key=lambda n: -deg.get(n.get("id"), 0))
        ft = Counter(n.get("file_type") for n in members)
        comm_tasks.append({
            "community_id": cid,
            "current_label": cur or f"Community {cid}",
            "size": len(members),
            "file_types": dict(ft),
            "top_members": [n.get("label") for n in members_sorted[:18]],
            "source_files": sorted({n.get("source_file") for n in members_sorted[:18]
                                    if n.get("source_file")})[:8],
        })

    # ---- vague / inferred connections ------------------------------------ #
    rel_tasks = []
    done_rel = set((audit.get("relations") or {}).keys())
    if not args.no_relations:
        for i, l in enumerate(_links(g)):
            rel = l.get("relation")
            conf = (l.get("confidence") or "").upper()
            vague = rel in VAGUE_RELATIONS or rel not in STRUCTURAL_RELATIONS and conf in {"INFERRED", "AMBIGUOUS"}
            if rel in STRUCTURAL_RELATIONS and conf not in {"INFERRED", "AMBIGUOUS"}:
                vague = False
            if not vague:
                continue
            if str(i) in done_rel and not args.force:
                continue
            s, t = id2node.get(l.get("source")), id2node.get(l.get("target"))
            if not s or not t:
                continue
            rel_tasks.append({
                "link_index": i,
                "current_relation": rel,
                "confidence": l.get("confidence"),
                "source_label": s.get("label"),
                "source_type": s.get("file_type"),
                "target_label": t.get("label"),
                "target_type": t.get("file_type"),
                "source_file": l.get("source_file"),
            })
            if len(rel_tasks) >= args.max_relations:
                break

    # ---- cryptic nodes (conservative) ------------------------------------ #
    node_tasks = []
    if args.nodes:
        done_node = set((audit.get("nodes") or {}).keys())
        for n in _nodes(g):
            lbl = (n.get("label") or "").strip()
            nid = n.get("id")
            cryptic = (
                lbl == nid
                or (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,2}", lbl) is not None)
                or (re.fullmatch(r"[a-z0-9]{16,}", lbl) is not None)  # hash-ish
            )
            if not cryptic or (nid in done_node and not args.force):
                continue
            node_tasks.append({
                "node_id": nid,
                "current_label": lbl,
                "file_type": n.get("file_type"),
                "source_file": n.get("source_file"),
                "degree": deg.get(nid, 0),
            })
            if len(node_tasks) >= args.max_nodes:
                break

    tasks = {
        "graphify_out": str(out),
        "generated": _now(),
        "instructions": (
            "You are Claude naming a knowledge graph IN-AGENT (do NOT call Ollama/"
            "Gemini). For each community write a 2-5 word Title Case name from its "
            "members (e.g. 'Mask Tracing UI', 'Training Pipeline'). For each "
            "relation pick ONE precise lowercase snake_case predicate describing how "
            "source acts on target (e.g. configures, validates, persists, renders, "
            "schedules, authenticates, depends_on, derived_from). Only include items "
            "you can improve; omit the rest. Write your answer to names.json with "
            "shape {\"communities\":{\"<id>\":\"Name\"}, \"relations\":{\"<idx>\":"
            "\"predicate\"}, \"nodes\":{\"<node_id>\":\"Better Label\"}}."
        ),
        "communities": comm_tasks,
        "relations": rel_tasks,
        "nodes": node_tasks,
    }
    dest = out / "naming_tasks.json"
    _write_json(dest, tasks)

    print(f"PLAN written to {dest}")
    print(f"  communities needing names : {len(comm_tasks)}")
    print(f"  connections to upgrade    : {len(rel_tasks)}"
          f"{' (capped)' if len(rel_tasks) >= args.max_relations else ''}")
    print(f"  cryptic nodes flagged     : {len(node_tasks)}"
          + ("" if args.nodes else " (node pass off; use --nodes)"))
    total_comm = sum(1 for c in comms if c is not None)
    named = sum(1 for c in comms if c is not None
                and not is_generic_community(labels.get(str(c))))
    print(f"  communities total/named   : {total_comm}/{named}")
    if not comm_tasks and not rel_tasks and not node_tasks:
        print("  nothing to do - graph is already semantically named.")


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #

def _dedup_community_names(new_names: dict, existing_labels: dict) -> tuple[dict, int]:
    """Make every community name unique before it becomes a wiki *filename*.
    A name is 'taken' if a non-generic label on a community we are NOT renaming
    uses it, or it was already assigned earlier this pass. On collision, suffix
    ` (<cid>)`. Deterministic (cids in numeric order)."""
    def _cid_key(k):
        try:
            return (0, int(k))
        except (TypeError, ValueError):
            return (1, str(k))
    taken = {
        str(v).strip()
        for cid, v in (existing_labels or {}).items()
        if str(cid) not in new_names and not is_generic_community(v)
    }
    out: dict = {}
    collisions = 0
    for cid in sorted(new_names, key=_cid_key):
        name = str(new_names[cid]).strip()
        if not name or is_generic_community(name):
            out[cid] = new_names[cid]
            continue
        final = name
        if final in taken:
            final, n = f"{name} ({cid})", 2
            while final in taken:
                final = f"{name} ({cid}-{n})"
                n += 1
            collisions += 1
        taken.add(final)
        out[cid] = final
    return out, collisions


def cmd_apply(args) -> None:
    out = _out_dir(args.path)
    names = _read_json(Path(args.names) if args.names else out / "names.json")
    if not names:
        sys.exit("ERROR: names.json not found or empty. Write Claude's names there first.")

    g = _read_json(out / GRAPH)
    labels = _read_json(out / LABELS, {}) or {}
    audit = _read_json(out / AUDIT, {}) or {"created": _now()}
    audit.setdefault("communities", {})
    audit.setdefault("relations", {})
    audit.setdefault("nodes", {})
    audit["updated"] = _now()

    # backup graph + labels once per apply
    _backup(out / GRAPH)
    if (out / LABELS).exists():
        _backup(out / LABELS)

    # ---- communities ----------------------------------------------------- #
    # Community names become Obsidian wiki *filenames* - dedup so identical
    # sibling-cluster names don't collide and silently overwrite each other.
    comm_names, n_dups = _dedup_community_names(names.get("communities") or {}, labels)
    n_comm = 0
    for cid, name in comm_names.items():
        name = str(name).strip()
        if not name or is_generic_community(name):
            continue
        old = labels.get(str(cid))
        labels[str(cid)] = name
        audit["communities"][str(cid)] = {"old": old, "new": name}
        n_comm += 1

    # ---- relations ------------------------------------------------------- #
    links = _links(g)
    n_rel = 0
    for idx, predicate in (names.get("relations") or {}).items():
        predicate = _norm_predicate(predicate)
        try:
            l = links[int(idx)]
        except (ValueError, IndexError):
            continue
        if not predicate:
            continue
        old = l.get("relation")
        if "original_relation" not in l:
            l["original_relation"] = old
        l["relation"] = predicate
        l["relation_source"] = "claude-semantic"
        audit["relations"][str(idx)] = {"old": old, "new": predicate,
                                        "confidence": l.get("confidence")}
        n_rel += 1

    # ---- nodes ----------------------------------------------------------- #
    n_node = 0
    if names.get("nodes"):
        id2node = _id2node(g)
        for nid, lbl in names["nodes"].items():
            lbl = str(lbl).strip()
            n = id2node.get(nid)
            if not n or not lbl:
                continue
            old = n.get("label")
            if "original_label" not in n:
                n["original_label"] = old
            n["label"] = lbl
            # keep a searchable alias so the literal query matcher still hits the old token
            aliases = set(filter(None, [n.get("norm_label"), old]))
            n["aliases"] = sorted(aliases)
            audit["nodes"][nid] = {"old": old, "new": lbl}
            n_node += 1

    _write_json(out / GRAPH, g)
    _write_json(out / LABELS, {str(k): v for k, v in labels.items()})
    _write_json(out / AUDIT, audit)

    print(f"APPLIED: {n_comm} community names, {n_rel} relations, {n_node} node labels")
    if n_dups:
        print(f"  disambiguated {n_dups} colliding community name(s) with an id suffix")
    print(f"  graph.json + {LABELS} updated; audit -> {AUDIT}")
    print("Next: run `regenerate` to rebuild the report + wiki, then sync the vault.")


def _norm_predicate(p) -> str:
    p = str(p or "").strip().lower()
    p = re.sub(r"[\s\-]+", "_", p)
    p = re.sub(r"[^a-z0-9_]", "", p)
    return p


def _backup(p: Path) -> None:
    bak = p.with_suffix(p.suffix + ".prelabel.bak")
    if not bak.exists():
        shutil.copy2(p, bak)


# --------------------------------------------------------------------------- #
# regenerate
# --------------------------------------------------------------------------- #

def cmd_regenerate(args) -> None:
    out = _out_dir(args.path)
    project_root = out.parent
    py = _python_for(out)

    labels = _read_json(out / LABELS, {}) or {}
    ok_report = _regen_report(out, py, labels) if py else False

    # CLI exporters. wiki is the vault-facing, per-community format, so ALWAYS
    # (re)build it - even if this project never had one - otherwise renamed
    # labels never reach Obsidian (the #1 silent failure this skill prevents).
    # html/obsidian are only refreshed if already present; we never newly
    # create obsidian/ (it is one markdown file PER NODE).
    did = []
    if py:
        if _run_export(py, project_root, "wiki"):
            did.append("wiki")
        for fmt, marker in [("html", "graph.html"), ("obsidian", "obsidian")]:
            if (out / marker).exists() and _run_export(py, project_root, fmt):
                did.append(fmt)

    if not ok_report:
        _text_fallback(out)  # guarantee the report at least reflects new names

    print(f"REGENERATE: report={'api' if ok_report else 'text-fallback'}; "
          f"exports={did or 'none'}")
    print("To mirror into a notes vault: copy GRAPH_REPORT.md + wiki/ ONLY - never "
          "the whole graphify-out, never obsidian/ (one markdown file per node).")


def _python_for(out: Path) -> str | None:
    mark = out / PYMARK
    if mark.exists():
        c = mark.read_text(encoding="utf-8").strip()
        if c and _imports_graphify(c):
            return c
    for c in _interpreter_candidates():
        if c and _imports_graphify(c):
            mark.write_text(c, encoding="utf-8")
            return c
    return None


def _regen_report(out: Path, py: str, labels: dict) -> bool:
    """Rebuild GRAPH_REPORT.md via graphify's own report.generate, using the
    existing clustering (node.community) - NEVER re-cluster."""
    helper = r'''
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
lbl_path = out/".graphify_labels.json"
raw = json.loads(lbl_path.read_text(encoding="utf-8")) if lbl_path.exists() else {}
labels = {int(k): v for k, v in raw.items()}
data = json.loads((out/"graph.json").read_text(encoding="utf-8"))
import networkx as nx
try:
    G = nx.node_link_graph(data, edges="links")
except TypeError:
    G = nx.node_link_graph(data)
communities = {}
for n in data["nodes"]:
    communities.setdefault(n.get("community"), []).append(n.get("id"))
communities = {int(k): v for k, v in communities.items() if k is not None}
# report.generate expects a label for EVERY community (graphify Step 5 invariant)
for cid in communities:
    labels.setdefault(cid, "Community %d" % cid)
from graphify.cluster import score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
questions = suggest_questions(G, communities, labels)
detect_p = out/".graphify_detect.json"
if detect_p.exists():
    detection = json.loads(detect_p.read_text(encoding="utf-8"))
else:
    # graphify cleans up .graphify_detect.json - synthesize the 2 fields the
    # report needs (total_files, total_words) from the graph + existing report.
    import re as _re
    srcs = {n.get("source_file") for n in data["nodes"] if n.get("source_file")}
    total_words = 0
    rp = out/"GRAPH_REPORT.md"
    if rp.exists():
        m = _re.search(r"([\d,]+)\s+files\D+~?([\d,]+)\s+words", rp.read_text(encoding="utf-8"))
        if m:
            total_words = int(m.group(2).replace(",", ""))
    detection = {"total_files": len(srcs), "total_words": total_words}
report = generate(G, communities, cohesion, labels, gods, surprises, detection,
                  {"input":0,"output":0}, str(out.parent), suggested_questions=questions)
(out/"GRAPH_REPORT.md").write_text(report, encoding="utf-8")
print("report-ok")
'''
    try:
        r = subprocess.run([py, "-c", helper, str(out)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and "report-ok" in r.stdout:
            return True
        print("INFO: API report regen failed; using text fallback.\n"
              + (r.stderr or "")[-600:], file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"INFO: API report regen errored ({e}); text fallback.", file=sys.stderr)
    return False


def _run_export(py: str, cwd: Path, fmt: str) -> bool:
    try:
        r = subprocess.run([py, "-m", "graphify", "export", fmt],
                           cwd=str(cwd), capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            return True
        print(f"INFO: export {fmt} failed: {(r.stderr or '')[-300:]}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"INFO: export {fmt} errored: {e}", file=sys.stderr)
    return False


def _text_fallback(out: Path) -> None:
    """Substitute renamed community labels straight into any already-materialised
    markdown so the vault stays consistent even without graphify's exporters."""
    audit = _read_json(out / AUDIT, {}) or {}
    comm = audit.get("communities") or {}
    if not comm:
        return
    repl = []
    for cid, ch in comm.items():
        new = ch.get("new")
        if not new:
            continue
        for old in (f"Community {cid}", f"Community_{cid}"):
            repl.append((old, new))
            repl.append((old.replace(" ", "_"), new.replace(" ", "_")))
    targets = [out / "GRAPH_REPORT.md"]
    wiki = out / "wiki"
    if wiki.is_dir():
        targets += list(wiki.glob("*.md"))
    n = 0
    for p in targets:
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        new = txt
        for a, b in repl:
            new = new.replace(a, b)
        if new != txt:
            p.write_text(new, encoding="utf-8")
            n += 1
    print(f"  text-fallback updated {n} markdown file(s).")


# --------------------------------------------------------------------------- #
# status / revert
# --------------------------------------------------------------------------- #

def cmd_status(args) -> None:
    out = _out_dir(args.path)
    g = _read_json(out / GRAPH)
    labels = _read_json(out / LABELS, {}) or {}
    comms = _by_community(g)
    total = sum(1 for c in comms if c is not None)
    named = sum(1 for c in comms if c is not None
                and not is_generic_community(labels.get(str(c))))
    rels = _links(g)
    upgraded = sum(1 for l in rels if l.get("relation_source") == "claude-semantic")
    vague = sum(1 for l in rels if l.get("relation") in VAGUE_RELATIONS)
    print(f"graphify-out: {out}")
    print(f"  communities : {named}/{total} named "
          f"({total - named} still generic)")
    print(f"  connections : {upgraded} upgraded; {vague} still vague")


def cmd_revert(args) -> None:
    out = _out_dir(args.path)
    for f in (GRAPH, LABELS):
        bak = (out / f).with_suffix(Path(f).suffix + ".prelabel.bak")
        if bak.exists():
            shutil.copy2(bak, out / f)
            print(f"reverted {f}")
    print("Reverted to pre-label backups. Re-run `regenerate` to rebuild outputs.")


# --------------------------------------------------------------------------- #
# merge (combine chunked names_part_*.json from large-graph naming)
# --------------------------------------------------------------------------- #

def cmd_merge(args) -> None:
    out = _out_dir(args.path)
    parts = sorted(out.glob("names_part_*.json"))
    if not parts:
        sys.exit(f"ERROR: no names_part_*.json in {out}. Nothing to merge.")
    communities: dict = {}
    relations: dict = {}
    nodes: dict = {}
    for p in parts:
        d = _read_json(p, {}) or {}
        if any(k in d for k in ("communities", "relations", "nodes")):
            communities.update(d.get("communities") or {})
            relations.update(d.get("relations") or {})
            nodes.update(d.get("nodes") or {})
        else:
            communities.update(d)  # a flat {cid: name} community map
    labels = _read_json(out / LABELS, {}) or {}
    communities, n_dups = _dedup_community_names(communities, labels)
    _write_json(out / "names.json",
                {"communities": communities, "relations": relations, "nodes": nodes})
    print(f"MERGED {len(parts)} part file(s) -> names.json: "
          f"{len(communities)} communities, {len(relations)} relations, "
          f"{len(nodes)} nodes")
    if n_dups:
        print(f"  disambiguated {n_dups} colliding community name(s)")
    if args.clean:
        removed = 0
        for pat in ("names_part_*.json", "chunk_*.json", "_dump_*.txt"):
            for f in out.glob(pat):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        print(f"  cleaned {removed} scratch file(s)")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(prog="semantic_rename.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_path(p):
        p.add_argument("path", nargs="?", default=None,
                       help="project root or graphify-out dir (default: ./graphify-out)")

    p = sub.add_parser("resolve-python"); add_path(p); p.set_defaults(fn=cmd_resolve_python)

    p = sub.add_parser("plan"); add_path(p)
    p.add_argument("--max-relations", type=int, default=300)
    p.add_argument("--max-nodes", type=int, default=120)
    p.add_argument("--no-relations", action="store_true")
    p.add_argument("--nodes", action="store_true", help="also flag cryptic node labels")
    p.add_argument("--force", action="store_true", help="re-plan items already in the audit")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("apply"); add_path(p)
    p.add_argument("--names", default=None, help="path to names.json (default: <out>/names.json)")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("regenerate"); add_path(p); p.set_defaults(fn=cmd_regenerate)
    p = sub.add_parser("status"); add_path(p); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("revert"); add_path(p); p.set_defaults(fn=cmd_revert)

    p = sub.add_parser("merge"); add_path(p)
    p.add_argument("--clean", action="store_true",
                   help="also delete scratch: names_part_*/chunk_*/_dump_*")
    p.set_defaults(fn=cmd_merge)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
