---
name: altabots-version-archive
description: Companion to altabots-agent-skill. Whenever a .bot/.flow is generated or published, archive it into a local git repo (permanent history — the AltaBots platform only keeps the 10 most recent versions and has no API to export a historical or current config back down). Auto-diffs against the previous version at the node/prompt-section level (FlowAgent, Workflow, and QuestionAnswer schemas) and auto-appends a factual changelog entry to CHANGELOG.md as part of the same command — no separate manual step. Can optionally auto-create a private GitHub repo (personal account or a GitHub Organization) via the GitHub API and push to it, with zero browser interaction. Can also restore/extract any archived historical version back out of git. Use whenever the user builds/updates/publishes an AltaBots Agent, FlowAgent, or Workflow and wants the change permanently recorded, or asks to set up version tracking / changelog / git archiving / cloud backup for an AltaBots agent.
license: MIT
metadata:
  version: 2.1.0
  generatedBy: altabots-version-archive
  customizedBy: gray
---

# AltaBots Version Archive

Solves a specific gap left open by `altabots-agent-skill`: the AltaBots platform's
own version list only keeps the **10 most recent** versions, and its public API has
**no endpoint to export a historical (or even the current) `.bot`/`.flow` config**
— confirmed against `references/call-altabots-api.md` and
`references/test-mode-update-publish.md` in `altabots-agent-skill`; the only
version-related endpoints are `version/import` (write) and `version/release`
(write). So the only durable record of "what did version N actually look like"
has to be kept locally — this skill keeps it in git.

It only covers changes that pass through a local `.bot`/`.flow` file (i.e. built or
edited via `altabots-agent-skill`, or exported from the console). It has no way to
see a change made directly in the console that was never exported — there is no
platform webhook or export API to catch that automatically. If the team edits
directly in console sometimes, that gap is a process decision (e.g. "always export
after a console edit"), not something this skill can close on its own.

## When to use

- Right after `altabots-agent-skill` generates or updates a `.bot`/`.flow`.
- Right after `scripts/publish_altabots.py` (in `altabots-agent-skill`) returns a
  `version` number, to tag the corresponding commit.
- When the user asks to set up version tracking / a changelog / git backup for an
  AltaBots agent project, or wants to pull an old version back out.

## Package layout

```
SKILL.md
scripts/
  archive_to_git.py     # commit + tag + auto-changelog (+ optional auto-created GitHub remote) (the main entry point)
  diff_bot_nodes.py      # structural diff between two .bot/.flow snapshots (used internally by archive_to_git.py)
  clean_bot_diff.py      # git textconv helper: hides volatile fields (exportTime) from `git diff`/`git log -p`
  restore_version.py     # the reverse direction: extract a historical version back out of the git archive
  test_skill.py          # regression tests — run after editing any script here: python3 test_skill.py
```

## Schemas `diff_bot_nodes.py` understands

Confirmed against real exports — these three are NOT interchangeable:

| botType | Node list at | Node id type | Prompt field |
|---|---|---|---|
| FlowAgent (`.bot`) | `flowRule.components` | int | `messages` (list of `{type, text}` blocks: Role/LongMemory/ShortMemory/Plugin/Input/...) |
| Workflow (`.flow`) | `workflow.workflowNodes` (+ `workflow.workflowEdges` for routing) | string | `llmParam.userPrompt` (single string) |
| QuestionAnswer (`.bot`, no flowRule) | — (flat) | — | `prompt` (top-level string) |

`x`/`y` (canvas position) are ignored on nodes. `exportTime` is always ignored at
the top level. For `messages` and `llmParam`, the diff is broken down per prompt
section / per key instead of dumping the whole field as one opaque truncated blob
— this is the level a hand-written changelog describes changes at ("Role 段落新增
規則...", not "messages changed").

**Unverified assumption**: node/edge matching is by `id`, assuming the platform
preserves ids across re-exports of the same agent. Not confirmed against the
platform's actual export behavior — if ids ever get reassigned, an unchanged node
could misreport as removed+added. Flagged here rather than silently assumed away.

## Usage

**One command does the whole thing** — archive, diff against the previous
version, and append a factual `CHANGELOG.md` entry, all as part of the same call:

```
python3 scripts/archive_to_git.py <file.bot> [--repo-dir DIR] [--message "..."] [--version 1.0.3] [--push]
```

- Repo dir defaults to the file's own parent folder (the existing convention: one
  project folder = one repo, e.g. `altabots-my-agent-project/`). Pass `--repo-dir`
  to use or create a different location.
- `git init`s the repo on first use, writes `.gitignore` (excludes `__pycache__/`,
  `.env`, `*.key`, anything key-shaped — **never commit the AltaBots API key**),
  and registers the `clean_bot_diff.py` textconv driver via `.gitattributes` so
  `git diff` / `git log -p` don't show noise from platform-regenerated fields.
- Commits only if the file's raw bytes actually changed. A byte-identical
  re-export is a no-op commit, but a `--version` tag is still attached to
  whatever the current content-equivalent commit is — so a version number is
  never left untraceable just because nothing substantive changed.
- With `--version`, tags the content commit `altabots-v<version>`.
- **Auto-changelog** (default on; `--no-changelog` to skip): if there's a
  previous commit for this file, runs `diff_bot_nodes.py` against it and
  appends a `| 調整節點 | 調整類型 | 調整內容 |` table to `CHANGELOG.md`, as its
  own follow-up commit (so the version tag still points cleanly at the content
  commit, not the docs commit). **Facts only** — which node/field/prompt-section
  changed, with real before/after text. It does NOT invent the business *why*
  or map to a known-issues list; add that by hand (or have the invoking skill
  add it) as a manual edit to the generated entry if you have that context —
  never fabricate a "已知問題" table the user didn't give you.
- With `--push`, pushes branch + tags to `origin` **only if that remote is
  already configured**. On its own, `--push` still never creates or
  configures a remote — repo creation is opt-in (below), not automatic.

**Auto-creating the cloud repo** (no browser needed — pure GitHub API):
```
python3 scripts/archive_to_git.py <file.bot> --push --create-remote \
    [--remote-name <project-name>] [--github-org <org>] [--github-token <token>]
```
- Add `--create-remote` alongside `--push`, and if `origin` isn't configured
  yet, it creates a new **private** GitHub repo via the GitHub REST API
  (`POST /user/repos` or, with `--github-org`, `POST /orgs/<org>/repos`),
  sets it as `origin`, then pushes — end to end, no manual "create
  repository" step in a browser.
- **What the person running it needs**: a GitHub Personal Access Token with
  repo-creation scope, set once as `GITHUB_TOKEN` (or passed via
  `--github-token`); optionally `GITHUB_ORG`/`--github-org` if the target is
  a company Organization rather than their own personal account; and a
  project name (`--remote-name`, defaults to the repo folder's name) so
  each project lands in its own distinctly-named repo.
- Always creates the repo **private** — never defaults to public.
- If `origin` already exists, `--create-remote` is a no-op (never
  recreates/overwrites an existing remote) — it only fills the gap when
  there's nowhere to push yet.
- Fails with a clear message (exit 3) if no token is available, or if the
  GitHub API itself errors (e.g. name collision) — never leaves the repo in
  a half-configured state.

**Restoring an old version** (the reverse direction — git back out to a file
ready to re-publish):
```
python3 scripts/restore_version.py <repo-dir> altabots-v1.0.2 <filename> [-o output.bot]
```
Read-only — it only extracts the file and prints the `publish_altabots.py`
command you'd run next to actually put it live (which is your call, not this
script's).

## Constraints

- Never write the AltaBots API key into any file in the repo — it's handled
  entirely by `publish_altabots.py` (in `altabots-agent-skill`) via `--api-key` /
  `ALTABOTS_API_KEY`, and this skill never touches it.
- Don't invent a "已知問題" / feedback mapping if the user hasn't given you one —
  leave that section out rather than guessing why a change was made.
- Don't silently push to a remote that doesn't already exist, and don't auto-create
  one unless `--create-remote` was explicitly passed. Which cloud, whose account,
  and repo visibility for client-sensitive content are decisions the user/org
  makes explicitly by passing that flag — never default into creating cloud
  infrastructure on your own initiative.
- A newly auto-created repo (`--create-remote`) is always private. Never pass
  a flag that would make it public without the user explicitly asking for that.
- After editing any script in `scripts/`, run `python3 scripts/test_skill.py` —
  it locks in behaviors that previously regressed silently (e.g. the Workflow
  schema being misdetected as FlowAgent, or a no-op commit skipping its tag).
