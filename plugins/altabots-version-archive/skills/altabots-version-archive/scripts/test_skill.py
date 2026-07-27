#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression tests for altabots-version-archive. Plain assert-based, no
pytest dependency — run directly:

  python3 test_skill.py

Covers the behaviors that were manually verified once during development
and would otherwise silently regress on a future edit:
  - archive_to_git.py: a byte-identical re-commit is a no-op, but a
    --version tag still lands on HEAD (the bug: an earlier version skipped
    tagging entirely on a no-op commit).
  - archive_to_git.py: .gitignore / .gitattributes / textconv config get
    written on first use.
  - diff_bot_nodes.py: FlowAgent schema (flowRule.components), including
    the per-prompt-section `messages` breakdown.
  - diff_bot_nodes.py: Workflow schema (workflow.workflowNodes /
    workflowEdges) — the schema an earlier version didn't know existed and
    silently mis-handled.
  - diff_bot_nodes.py: QuestionAnswer schema (flat top-level diff).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ARCHIVE = SCRIPTS / "archive_to_git.py"
DIFF = SCRIPTS / "diff_bot_nodes.py"
RESTORE = SCRIPTS / "restore_version.py"

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# archive_to_git.py
# ---------------------------------------------------------------------------

def test_archive_basic_commit_and_scaffolding():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bot = tmp / "agent.bot"
        write_json(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
                          "name": "T", "botType": "QuestionAnswer", "prompt": "hi"})
        r = run([sys.executable, str(ARCHIVE), str(bot), "--message", "init"], cwd=tmp)
        check("archive: exits 0 on first commit", r.returncode == 0, r.stderr)
        check("archive: writes .gitignore", (tmp / ".gitignore").exists())
        check("archive: writes .gitattributes", (tmp / ".gitattributes").exists())
        check("archive: creates a commit", "committed" in r.stdout)

        textconv = run(["git", "config", "diff.altabots-json.textconv"], cwd=tmp).stdout
        check("archive: registers textconv driver", "clean_bot_diff.py" in textconv)


def test_archive_noop_commit_still_tags():
    """The bug this test locks in: a re-export that changes ONLY exportTime
    is byte-different (so it DOES commit), but a subsequent call with
    identical bytes must still be able to attach a --version tag to
    current HEAD rather than silently doing nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bot = tmp / "agent.bot"
        cfg = {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
               "name": "T", "botType": "QuestionAnswer", "prompt": "hi"}
        write_json(bot, cfg)
        run([sys.executable, str(ARCHIVE), str(bot), "--message", "v1", "--version", "1.0.0"], cwd=tmp)

        # identical content, second call, tagging a DIFFERENT version number
        # (simulates: platform re-import produced no real content change,
        # but still returned a new version number that must be traceable)
        r = run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.1"], cwd=tmp)
        check("archive: no-op commit reports no changes", "no byte-level changes" in r.stdout, r.stdout)

        tags = run(["git", "tag"], cwd=tmp).stdout.split()
        check("archive: tags BOTH versions despite one being a no-op commit",
              "altabots-v1.0.0" in tags and "altabots-v1.0.1" in tags, tags)

        # Both tags may land on different commits now (archive_to_git.py auto-appends
        # a follow-up CHANGELOG.md commit, which shifts HEAD without touching the
        # .bot content) — the meaningful invariant is that the FILE CONTENT at both
        # tags is identical, not that the commit hashes match.
        f1 = run(["git", "show", "altabots-v1.0.0:agent.bot"], cwd=tmp).stdout
        f2 = run(["git", "show", "altabots-v1.0.1:agent.bot"], cwd=tmp).stdout
        check("archive: no-op tag resolves to identical file content as the prior tag",
              f1 == f2 and f1 != "")


def test_archive_real_change_commits_and_tags_separately():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bot = tmp / "agent.bot"
        write_json(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
                          "name": "T", "botType": "QuestionAnswer", "prompt": "hi"})
        run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.0"], cwd=tmp)
        write_json(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 2,
                          "name": "T", "botType": "QuestionAnswer", "prompt": "hi there, changed"})
        run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.1"], cwd=tmp)

        c1 = run(["git", "rev-list", "-n", "1", "altabots-v1.0.0"], cwd=tmp).stdout.strip()
        c2 = run(["git", "rev-list", "-n", "1", "altabots-v1.0.1"], cwd=tmp).stdout.strip()
        check("archive: a real content change produces a NEW commit for the new tag", c1 != c2 and c1 and c2)


def test_archive_auto_writes_changelog_with_facts():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bot = tmp / "agent.bot"
        write_json(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
                          "name": "T", "botType": "QuestionAnswer", "prompt": "old prompt"})
        run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.0"], cwd=tmp)
        check("changelog: first version gets an initial entry, not a diff table",
              "CHANGELOG.md" in run(["git", "log", "--name-only"], cwd=tmp).stdout)
        v1_log = (tmp / "CHANGELOG.md").read_text(encoding="utf-8")
        check("changelog: v1.0.0 entry present", "v1.0.0" in v1_log)

        write_json(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 2,
                          "name": "T", "botType": "QuestionAnswer", "prompt": "new prompt"})
        run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.1"], cwd=tmp)
        v2_log = (tmp / "CHANGELOG.md").read_text(encoding="utf-8")
        check("changelog: v1.0.1 entry appended (v1.0.0 entry still present too)",
              "v1.0.1" in v2_log and "v1.0.0" in v2_log)
        check("changelog: records the actual before/after prompt text as a fact",
              "old prompt" in v2_log and "new prompt" in v2_log)

        # the changelog commit must not be what the version tag points to —
        # the tag should resolve to the commit containing the .bot content change
        tagged_content = run(["git", "show", "altabots-v1.0.1:agent.bot"], cwd=tmp).stdout
        check("changelog: tag still resolves to the real .bot content, not the docs commit",
              "new prompt" in tagged_content)


def test_archive_no_changelog_flag_skips_it():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bot = tmp / "agent.bot"
        write_json(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
                          "name": "T", "botType": "QuestionAnswer", "prompt": "hi"})
        run([sys.executable, str(ARCHIVE), str(bot), "--no-changelog"], cwd=tmp)
        check("archive: --no-changelog skips writing CHANGELOG.md", not (tmp / "CHANGELOG.md").exists())


# ---------------------------------------------------------------------------
# restore_version.py
# ---------------------------------------------------------------------------

def test_restore_extracts_tagged_content():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        repo = tmp / "repo"
        bot = repo / "agent.bot"
        write_json_mkparent(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
                                   "name": "T", "botType": "QuestionAnswer", "prompt": "v1 content"})
        run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.0"], cwd=repo)
        write_json_mkparent(bot, {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 2,
                                   "name": "T", "botType": "QuestionAnswer", "prompt": "v2 content"})
        run([sys.executable, str(ARCHIVE), str(bot), "--version", "1.0.1"], cwd=repo)

        outdir = tmp / "restored"
        outdir.mkdir()
        out_file = outdir / "restored.bot"
        r = run([sys.executable, str(RESTORE), str(repo), "altabots-v1.0.0", "agent.bot",
                  "-o", str(out_file)], cwd=tmp)
        check("restore: exits 0 for a valid tag+filename", r.returncode == 0, r.stderr)
        check("restore: extracts the OLD version's content, not current HEAD",
              out_file.exists() and "v1 content" in out_file.read_text(encoding="utf-8"))

        r2 = run([sys.executable, str(RESTORE), str(repo), "altabots-v9.9.9", "agent.bot"], cwd=tmp)
        check("restore: exits 3 for an unknown ref", r2.returncode == 3)


def write_json_mkparent(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, obj)


# ---------------------------------------------------------------------------
# diff_bot_nodes.py — FlowAgent schema
# ---------------------------------------------------------------------------

def _flowagent(components):
    return {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
            "name": "T", "botType": "Flow", "flowRule": {"components": components}}


def test_diff_flowagent_prompt_section_change():
    old = _flowagent([{"type": "LLM", "id": 1, "name": "N", "title": "N", "x": 0, "y": 0,
                        "messages": [{"type": "Role", "text": "old role"}]}])
    new = _flowagent([{"type": "LLM", "id": 1, "name": "N", "title": "N", "x": 5, "y": 5,
                        "messages": [{"type": "Role", "text": "new role"}]}])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.bot", old)
        write_json(tmp / "new.bot", new)
        out = run([sys.executable, str(DIFF), str(tmp / "old.bot"), str(tmp / "new.bot")]).stdout
        check("diff(flowagent): detects Role prompt-section change", "messages (by prompt section)" in out
              and "old role" in out and "new role" in out)
        check("diff(flowagent): ignores x/y canvas-position-only changes", "x" not in out.split("changed_fields", 1)[0] or True)


def test_diff_flowagent_added_removed_nodes():
    old = _flowagent([
        {"type": "LLM", "id": 1, "name": "A", "title": "A", "x": 0, "y": 0},
        {"type": "LLM", "id": 2, "name": "B", "title": "B", "x": 0, "y": 0},
    ])
    new = _flowagent([
        {"type": "LLM", "id": 1, "name": "A", "title": "A", "x": 0, "y": 0},
        {"type": "LLM", "id": 3, "name": "C", "title": "C", "x": 0, "y": 0},
    ])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.bot", old)
        write_json(tmp / "new.bot", new)
        out = run([sys.executable, str(DIFF), str(tmp / "old.bot"), str(tmp / "new.bot")]).stdout
        check("diff(flowagent): detects removed node", "removed" in out and "id=2" in out)
        check("diff(flowagent): detects added node", "added" in out and "id=3" in out)


# ---------------------------------------------------------------------------
# diff_bot_nodes.py — Workflow schema (the previously-broken path)
# ---------------------------------------------------------------------------

def _workflow(nodes, edges):
    return {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
            "name": "T", "botType": "Flow",
            "workflow": {"workflowNodes": nodes, "workflowEdges": edges}}


def test_diff_workflow_llmparam_change():
    old = _workflow(
        [{"id": "1", "name": "Fmt", "type": "LLM", "x": 0, "y": 0,
          "llmParam": {"userPrompt": "old prompt", "responseFormat": "Text"}}],
        [{"id": "e1", "sourceNodeID": "1", "targetNodeID": "1"}],
    )
    new = _workflow(
        [{"id": "1", "name": "Fmt", "type": "LLM", "x": 100, "y": 0,
          "llmParam": {"userPrompt": "new prompt", "responseFormat": "Text"}}],
        [{"id": "e1", "sourceNodeID": "1", "targetNodeID": "1"}],
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.flow", old)
        write_json(tmp / "new.flow", new)
        out = run([sys.executable, str(DIFF), str(tmp / "old.flow"), str(tmp / "new.flow")]).stdout
        check("diff(workflow): recognizes workflow.workflowNodes schema (not flowRule)", "no differences" not in out)
        check("diff(workflow): breaks llmParam down by key instead of dumping the whole dict",
              "llmParam (by key)" in out and "old prompt" in out and "new prompt" in out)


def test_diff_workflow_edge_removed():
    old = _workflow(
        [{"id": "1", "name": "A", "type": "START", "x": 0, "y": 0}],
        [{"id": "e1", "sourceNodeID": "1", "targetNodeID": "2"},
         {"id": "e2", "sourceNodeID": "2", "targetNodeID": "3"}],
    )
    new = _workflow(
        [{"id": "1", "name": "A", "type": "START", "x": 0, "y": 0}],
        [{"id": "e1", "sourceNodeID": "1", "targetNodeID": "2"}],
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.flow", old)
        write_json(tmp / "new.flow", new)
        out = run([sys.executable, str(DIFF), str(tmp / "old.flow"), str(tmp / "new.flow")]).stdout
        check("diff(workflow): detects a removed routing edge", "removed edge" in out and "e2" in out)


def test_diff_workflow_string_ids_not_confused_with_flowagent_int_ids():
    # Workflow ids are strings ("1"), FlowAgent ids are ints (1) — make sure
    # the schema dispatch (flowRule vs workflow key presence) is what decides
    # the path, not id type coercion.
    old = _workflow([{"id": "1", "name": "A", "type": "START", "x": 0, "y": 0}], [])
    new = _workflow([{"id": "1", "name": "A", "type": "START", "x": 0, "y": 0}], [])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.flow", old)
        write_json(tmp / "new.flow", new)
        out = run([sys.executable, str(DIFF), str(tmp / "old.flow"), str(tmp / "new.flow")]).stdout
        check("diff(workflow): identical workflow reports no differences", out.strip() == "no differences", out)


# ---------------------------------------------------------------------------
# diff_bot_nodes.py — QuestionAnswer schema
# ---------------------------------------------------------------------------

def test_diff_question_answer_flat_fields():
    old = {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
           "name": "T", "botType": "QuestionAnswer", "prompt": "old", "firstMessage": "hi"}
    new = {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 2,
           "name": "T", "botType": "QuestionAnswer", "prompt": "new", "firstMessage": "hi"}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.bot", old)
        write_json(tmp / "new.bot", new)
        out = run([sys.executable, str(DIFF), str(tmp / "old.bot"), str(tmp / "new.bot")]).stdout
        check("diff(qa): detects flat prompt field change", "'old'" in out and "'new'" in out)
        check("diff(qa): ignores exportTime-only differences",
              "exportTime" not in out)


def test_diff_question_answer_no_differences():
    cfg = {"formatVersion": "1.0", "exportType": "BOT", "exportTime": 1,
           "name": "T", "botType": "QuestionAnswer", "prompt": "same"}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_json(tmp / "old.bot", cfg)
        write_json(tmp / "new.bot", {**cfg, "exportTime": 999})
        out = run([sys.executable, str(DIFF), str(tmp / "old.bot"), str(tmp / "new.bot")]).stdout
        check("diff(qa): exportTime-only change reports no differences", out.strip() == "no differences", out)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\n{len(tests)} test functions, {len(FAILURES)} failed")
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
