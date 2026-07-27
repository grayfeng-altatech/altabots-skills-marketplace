#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Structural diff between two .bot/.flow snapshots, at the node/component
level. This is the grounded input a skill uses to WRITE a business-readable
changelog entry (the "調整節點 / 調整類型 / 調整內容" table style used in
hand-maintained version docs), instead of relying on someone's memory of
what they changed.

Handles THREE distinct schemas confirmed against real exports — these are
NOT interchangeable, an earlier version of this script only handled the
first one and silently fell back to a useless whole-blob diff for the
second:
  - FlowAgent (`.bot`, botType=Flow): nodes at `flowRule.components`
    (`id` is an int), prompt at each node's `messages` (list of
    {type, text} blocks — Role/LongMemory/ShortMemory/Plugin/Input/...).
  - Workflow (`.flow`): nodes at `workflow.workflowNodes` (`id` is a
    STRING), edges at `workflow.workflowEdges` (diffed separately —
    routing changes), prompt at an LLM node's `llmParam.userPrompt`
    (a single string, not a message-block list).
  - QuestionAnswer Agent (`.bot`, no flowRule/workflow): flat top-level
    fields, prompt directly at `prompt`.

Canvas position (`x`, `y`) is ignored on nodes — layout, not behavior.
`exportTime` is always ignored at the top level (the platform regenerates
it on every export regardless of real changes).

CAVEAT (unverified): node/edge matching is by `id`. This assumes the
platform preserves component ids across re-exports of the same agent. That
assumption hasn't been confirmed against the platform's actual re-export
behavior — if ids ever get reassigned on export, unchanged nodes could
misreport as added+removed. Treat "no differences" / added / removed
results with that in mind until confirmed.

Usage:
  python3 diff_bot_nodes.py old.bot new.bot
  python3 diff_bot_nodes.py old.bot new.bot --json

Exit codes: 0 ok (prints "no differences" if none); 4 usage error.
"""
import argparse
import json
import sys
from pathlib import Path

IGNORED_TOP_LEVEL = {"exportTime"}
IGNORED_NODE_FIELDS = {"x", "y"}

# Fields whose value is itself a dict worth a key-level breakdown instead of
# one opaque truncated blob (e.g. Workflow LLM nodes: llmParam.userPrompt).
DICT_FIELDS_TO_EXPAND = {"llmParam", "modelDynamicParams"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def truncate(v, n=200):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def diff_messages(old_msgs, new_msgs):
    """FlowAgent LLM prompt: a list of {type, text} blocks. Diff text per
    block `type` instead of dumping the whole list as one opaque JSON
    string — this is what actually corresponds to a prompt-engineering
    change (hand-written changelogs call this out per "段落")."""
    old_by_type = {m.get("type"): m for m in (old_msgs or []) if isinstance(m, dict)}
    new_by_type = {m.get("type"): m for m in (new_msgs or []) if isinstance(m, dict)}
    out = {}
    for t in set(old_by_type) | set(new_by_type):
        o_text = (old_by_type.get(t) or {}).get("text", "")
        n_text = (new_by_type.get(t) or {}).get("text", "")
        if o_text != n_text:
            out[t] = {"old": truncate(o_text, 400), "new": truncate(n_text, 400)}
    return out


def diff_dict_field(old_d, new_d):
    """Shallow key-level diff for a dict-valued field (e.g. Workflow's
    llmParam: {userPrompt, responseFormat, chatModelVersionId}), so a
    userPrompt change is reported on its own instead of burying it inside
    a truncated dump of the whole dict."""
    old_d, new_d = old_d or {}, new_d or {}
    out = {}
    for k in set(old_d) | set(new_d):
        if old_d.get(k) != new_d.get(k):
            out[k] = {"old": truncate(old_d.get(k), 400), "new": truncate(new_d.get(k), 400)}
    return out


def diff_field(field_diffs, key, old_val, new_val):
    if key == "messages":
        d = diff_messages(old_val, new_val)
        if d:
            field_diffs["messages (by prompt section)"] = d
    elif key in DICT_FIELDS_TO_EXPAND and (isinstance(old_val, dict) or isinstance(new_val, dict)):
        d = diff_dict_field(old_val, new_val)
        if d:
            field_diffs[f"{key} (by key)"] = d
    else:
        field_diffs[key] = {"old": truncate(old_val), "new": truncate(new_val)}


def diff_node_list(old_nodes, new_nodes, id_key="id"):
    old_by_id = {n[id_key]: n for n in old_nodes}
    new_by_id = {n[id_key]: n for n in new_nodes}
    added = [new_by_id[i] for i in new_by_id if i not in old_by_id]
    removed = [old_by_id[i] for i in old_by_id if i not in new_by_id]
    changed = []
    for i in old_by_id:
        if i not in new_by_id:
            continue
        o, n = old_by_id[i], new_by_id[i]
        keys = (set(o.keys()) | set(n.keys())) - IGNORED_NODE_FIELDS
        field_diffs = {}
        for k in keys:
            if o.get(k) != n.get(k):
                diff_field(field_diffs, k, o.get(k), n.get(k))
        if field_diffs:
            changed.append({
                "id": i,
                "type": n.get("type", o.get("type")),
                "name": n.get("name") or n.get("title") or o.get("name") or o.get("title"),
                "changed_fields": field_diffs,
            })
    return added, removed, changed


def diff_edges(old_edges, new_edges):
    """Workflow routing (workflowEdges: sourceNodeID -> targetNodeID),
    matched by edge `id`. Reported separately from nodes — an edge
    add/remove is a routing change even if no node's own fields changed."""
    old_by_id = {e["id"]: e for e in (old_edges or [])}
    new_by_id = {e["id"]: e for e in (new_edges or [])}
    added = [e for i, e in new_by_id.items() if i not in old_by_id]
    removed = [e for i, e in old_by_id.items() if i not in new_by_id]
    return added, removed


def diff_top_level(old, new, exclude=()):
    keys = (set(old.keys()) | set(new.keys())) - IGNORED_TOP_LEVEL - set(exclude)
    field_diffs = {}
    for k in keys:
        if old.get(k) != new.get(k):
            field_diffs[k] = {"old": truncate(old.get(k)), "new": truncate(new.get(k))}
    return field_diffs


def render_field_diffs(lines, field_diffs, indent="    "):
    for k, v in field_diffs.items():
        if k.endswith("(by prompt section)") or k.endswith("(by key)"):
            lines.append(f"{indent}- {k}:")
            for section, sv in v.items():
                lines.append(f"{indent}    [{section}]")
                lines.append(f"{indent}      old: {sv['old']!r}")
                lines.append(f"{indent}      new: {sv['new']!r}")
        else:
            lines.append(f"{indent}- {k}: {v['old']!r} -> {v['new']!r}")


def render_nodes(lines, added, removed, changed, label="node"):
    for c in added:
        lines.append(f"+ added   [{c.get('type')}] {c.get('name') or c.get('title')} ({label} id={c.get('id')})")
    for c in removed:
        lines.append(f"- removed [{c.get('type')}] {c.get('name') or c.get('title')} ({label} id={c.get('id')})")
    for c in changed:
        lines.append(f"~ changed [{c['type']}] {c['name']} ({label} id={c['id']})")
        render_field_diffs(lines, c["changed_fields"])


def render_edges(lines, added, removed):
    for e in added:
        lines.append(f"+ added edge   {e.get('sourceNodeID')} -> {e.get('targetNodeID')} (edge id={e.get('id')})")
    for e in removed:
        lines.append(f"- removed edge {e.get('sourceNodeID')} -> {e.get('targetNodeID')} (edge id={e.get('id')})")


def diff_flowagent(old, new):
    old_comps = (old.get("flowRule") or {}).get("components", [])
    new_comps = (new.get("flowRule") or {}).get("components", [])
    added, removed, changed = diff_node_list(old_comps, new_comps, id_key="id")
    top = diff_top_level(
        {k: v for k, v in old.items() if k != "flowRule"},
        {k: v for k, v in new.items() if k != "flowRule"},
    )
    return {"schema": "flowagent", "added": added, "removed": removed, "changed": changed,
            "top_level_fields": top}


def diff_workflow(old, new):
    old_w, new_w = old.get("workflow") or {}, new.get("workflow") or {}
    added, removed, changed = diff_node_list(
        old_w.get("workflowNodes", []), new_w.get("workflowNodes", []), id_key="id")
    edge_added, edge_removed = diff_edges(old_w.get("workflowEdges", []), new_w.get("workflowEdges", []))
    top = diff_top_level(
        {k: v for k, v in old.items() if k != "workflow"},
        {k: v for k, v in new.items() if k != "workflow"},
    )
    return {"schema": "workflow", "added": added, "removed": removed, "changed": changed,
            "edges_added": edge_added, "edges_removed": edge_removed, "top_level_fields": top}


def diff_question_answer(old, new):
    top = diff_top_level(old, new)
    return {"schema": "question_answer", "top_level_fields": top}


def render_text(result):
    lines = []
    schema = result.get("schema")

    if schema in ("flowagent", "workflow"):
        label = "node"
        render_nodes(lines, result["added"], result["removed"], result["changed"], label=label)
        if schema == "workflow" and (result.get("edges_added") or result.get("edges_removed")):
            render_edges(lines, result["edges_added"], result["edges_removed"])
    top = result.get("top_level_fields") or {}
    if top:
        if lines:
            lines.append("")
        lines.append("Top-level fields changed:")
        render_field_diffs(lines, top, indent="  ")

    return "\n".join(lines) if lines else "no differences"


def main(argv):
    ap = argparse.ArgumentParser(description="Structural diff between two .bot/.flow snapshots")
    ap.add_argument("old", help="path to the previous version's .bot/.flow")
    ap.add_argument("new", help="path to the current version's .bot/.flow")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = ap.parse_args(argv)

    if not Path(args.old).is_file() or not Path(args.new).is_file():
        print("both files must exist", file=sys.stderr)
        return 4

    old, new = load(args.old), load(args.new)

    if isinstance(old.get("flowRule"), dict) or isinstance(new.get("flowRule"), dict):
        result = diff_flowagent(old, new)
    elif isinstance(old.get("workflow"), dict) or isinstance(new.get("workflow"), dict):
        result = diff_workflow(old, new)
    else:
        result = diff_question_answer(old, new)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
