#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archive a generated .bot/.flow into a local git repo (and optionally push to
a configured remote) — a permanent version history, since the AltaBots
platform only keeps the 10 most recent versions and has no API to export a
historical (or even the current) config back down.

Call this right after build_altabots_agent.py / build_altabots_workflow.py
produce a file, and again after publish_altabots.py returns a version
number (to tag the commit with it).

Usage:
  python3 archive_to_git.py my-agent.bot
  python3 archive_to_git.py my-agent.bot --repo-dir ~/agents/my-agent-project
  python3 archive_to_git.py my-agent.bot --message "調整表單文字" --version 1.0.9
  python3 archive_to_git.py my-agent.bot --push

What it does, in order:
  1. Picks a repo directory (default: the file's own parent folder) and
     `git init`s it if it isn't a repo yet.
  2. Writes .gitignore (once) so API keys / caches never get committed.
  3. Registers a textconv diff driver (clean_bot_diff.py, in this same
     scripts/ folder) via .gitattributes, so `git diff` / `git log -p` strip
     volatile fields like `exportTime` and only show real content changes.
  4. Copies the file into the repo, `git add`, `git commit` (skipped if the
     content is identical to the last commit).
  5. With --version, tags the commit `altabots-v<version>` — bridging this
     commit to the platform's own server-assigned version number.
  6. Unless --no-changelog: diffs against the previous commit of this same
     file (via diff_bot_nodes.py, imported directly) and appends a factual
     entry to CHANGELOG.md — which node/field changed, before/after text —
     as its own follow-up commit. This is FACTS ONLY (what changed); it does
     not invent a business reason *why*, or map to a known-issues list —
     add that by hand (or have a skill add it) if you have it.
  7. With --push, pushes branch+tags to 'origin' IF that remote is already
     configured. With --push --create-remote and no 'origin' yet, it will
     ALSO create that remote first: a new PRIVATE GitHub repo (via the
     GitHub API, using GITHUB_TOKEN/--github-token — never asks for a
     password), named after the repo folder unless --remote-name overrides
     it, then sets it as 'origin' and pushes. By default the repo is
     created under the token owner's own personal account; pass
     --github-org/GITHUB_ORG to create it under a GitHub Organization
     instead (e.g. once the company has one) — every project still gets
     its own distinctly-named repo either way, just under a different
     owner. Without --create-remote, a missing 'origin' is left alone
     (nothing pushed) — repo creation is opt-in, never automatic, because
     which cloud/account/visibility to use is a deliberate decision.

Exit codes: 0 ok (including no-op when nothing changed); 3 GitHub API error;
4 usage error.
"""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diff_bot_nodes  # noqa: E402

GITIGNORE = """\
__pycache__/
*.pyc
.env
*.key
*api_key*
*API_KEY*
"""


def run(cmd, cwd, check=True):
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def is_git_repo(path):
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                        cwd=str(path), capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def ensure_repo(repo_dir):
    repo_dir.mkdir(parents=True, exist_ok=True)
    if not is_git_repo(repo_dir):
        run(["git", "init"], cwd=repo_dir)
        print(f"initialized new git repo at {repo_dir}")

    gitignore = repo_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE, encoding="utf-8")
        run(["git", "add", ".gitignore"], cwd=repo_dir)

    gitattributes = repo_dir / ".gitattributes"
    if not gitattributes.exists():
        gitattributes.write_text("*.bot diff=altabots-json\n*.flow diff=altabots-json\n",
                                  encoding="utf-8")
        run(["git", "add", ".gitattributes"], cwd=repo_dir)

    helper = Path(__file__).resolve().parent / "clean_bot_diff.py"
    run(["git", "config", "diff.altabots-json.textconv", f"python3 {helper}"], cwd=repo_dir)

    name = run(["git", "config", "user.name"], cwd=repo_dir, check=False)
    if not name:
        local_name = getpass.getuser()
        run(["git", "config", "user.name", local_name], cwd=repo_dir)
        run(["git", "config", "user.email", f"{local_name}@local"], cwd=repo_dir)
        print(f"no git identity configured anywhere — set '{local_name} <{local_name}@local>' "
              f"for THIS repo only. Run `git config --global user.name/user.email` once to "
              f"set your real identity everywhere instead.")


def bot_summary(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("name", path.stem), data.get("botType") or data.get("exportType", "")
    except Exception:
        return path.stem, ""


def _diff_result(old_obj, new_obj):
    if isinstance(old_obj.get("flowRule"), dict) or isinstance(new_obj.get("flowRule"), dict):
        return diff_bot_nodes.diff_flowagent(old_obj, new_obj)
    if isinstance(old_obj.get("workflow"), dict) or isinstance(new_obj.get("workflow"), dict):
        return diff_bot_nodes.diff_workflow(old_obj, new_obj)
    return diff_bot_nodes.diff_question_answer(old_obj, new_obj)


def _changelog_rows(result):
    """Flatten a diff_bot_nodes result into (調整節點, 調整類型, 調整內容) rows.
    Facts only — deterministic, no invented business rationale."""
    rows = []
    for c in result.get("added", []):
        rows.append((f"{c.get('name') or c.get('title')} ({c.get('type')})", "新增節點", "—"))
    for c in result.get("removed", []):
        rows.append((f"{c.get('name') or c.get('title')} ({c.get('type')})", "移除節點", "—"))
    for c in result.get("changed", []):
        node = f"{c['name']} ({c['type']})"
        for field, v in c["changed_fields"].items():
            if isinstance(v, dict) and "old" in v:
                rows.append((node, field, f"{v['old']!r} → {v['new']!r}"))
            else:  # nested (by prompt section) / (by key) breakdown
                for section, sv in v.items():
                    rows.append((node, f"{field.split(' (')[0]}.{section}", f"{sv['old']!r} → {sv['new']!r}"))
    for k, v in (result.get("top_level_fields") or {}).items():
        rows.append(("(top-level)", k, f"{v['old']!r} → {v['new']!r}"))
    for e in result.get("edges_added", []) or []:
        rows.append(("(routing)", "新增連線", f"{e.get('sourceNodeID')} → {e.get('targetNodeID')}"))
    for e in result.get("edges_removed", []) or []:
        rows.append(("(routing)", "移除連線", f"{e.get('sourceNodeID')} → {e.get('targetNodeID')}"))
    return rows


def write_changelog(repo_dir, dest, version, message, author, has_parent):
    """Append a changelog entry for the commit that was JUST made (HEAD).
    Diffs against HEAD^'s copy of this same file, if any. Facts only — the
    business *why* is left for a human (or a skill reading this output) to
    add; never invents a known-issues mapping."""
    changelog = repo_dir / "CHANGELOG.md"
    date = datetime.now().strftime("%Y-%m-%d")
    label = f"v{version}" if version else run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir)
    header = f"\n## {label} — {date}\n\n**發佈人**: {author}　**摘要**: {message}\n"

    rows = []
    if has_parent:
        old_text = run(["git", "show", f"HEAD^:{dest.name}"], cwd=repo_dir, check=False)
        if old_text:
            try:
                old_obj = json.loads(old_text)
                new_obj = json.loads(dest.read_text(encoding="utf-8"))
                rows = _changelog_rows(_diff_result(old_obj, new_obj))
            except json.JSONDecodeError:
                pass  # previous revision wasn't valid JSON (shouldn't happen); skip the table, keep the header

    body = ""
    if rows:
        body = "\n| 調整節點 | 調整類型 | 調整內容 |\n|---|---|---|\n"
        body += "\n".join(f"| {n} | {t} | {d} |" for n, t, d in rows) + "\n"
    elif not has_parent:
        body = "\n初版建置存檔。\n"
    else:
        body = "\n(與上一版逐位元組相同,無實質內容變動)\n"

    with open(changelog, "a", encoding="utf-8") as f:
        f.write(header + body)

    run(["git", "add", "CHANGELOG.md"], cwd=repo_dir)
    run(["git", "commit", "-m", f"docs: changelog for {label}"], cwd=repo_dir)
    print(f"changelog: appended {label} entry ({len(rows)} row(s)) to CHANGELOG.md")


def create_github_repo(name, token, private=True, org=None, description=None,
                        api_base="https://api.github.com"):
    """Create a new repo via the GitHub REST API and return its SSH clone
    URL. Two destinations, both keyed off the SAME `name` argument so each
    project still lands in its own distinctly-named repo no matter which
    account/org owns it:
      - org=None: POST /user/repos      -> under the TOKEN OWNER's personal account
      - org="acme":  POST /orgs/acme/repos -> under that GitHub Organization
    Once the company has a GitHub Org, point every project at it with
    --github-org instead of switching to a different tool — same script,
    same per-project repo-per-project naming, different destination.

    `description` matters more than it looks: check_remote_exists.py's fuzzy
    match falls back to matching against a repo's description when the
    repo's (English, slug-shaped) name doesn't textually match what the
    user actually calls the project (e.g. a Chinese client name). Setting
    it here at creation time (via --project-label) is what makes that
    fallback able to find this repo again later.

    Always private unless the caller explicitly overrides — never default a
    freshly-created repo to public. Raises SystemExit with a clear message
    on any API error (name collision, bad/expired token, no org access,
    etc.) rather than leaving the repo in a half-configured state."""
    path = f"/orgs/{org}/repos" if org else "/user/repos"
    payload = {"name": name, "private": private}
    if description:
        payload["description"] = description
    req = urllib.request.Request(
        f"{api_base}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"GitHub API error creating repo {name!r}: HTTP {e.code}\n{body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"network error calling GitHub API: {e}")
    return data["ssh_url"]


def main(argv):
    ap = argparse.ArgumentParser(description="Archive a .bot/.flow into git as a permanent version history")
    ap.add_argument("file", help="path to the generated .bot or .flow file")
    ap.add_argument("--repo-dir", default=None,
                    help="git repo directory (default: the file's own parent folder)")
    ap.add_argument("--message", default=None, help="commit message summarizing this change")
    ap.add_argument("--version", default=None,
                    help="platform version number returned by publish_altabots.py; "
                         "tagged as altabots-v<version>")
    ap.add_argument("--push", action="store_true",
                    help="push branch+tags to 'origin' if that remote is configured")
    ap.add_argument("--create-remote", action="store_true",
                    help="if 'origin' isn't configured yet, create a new PRIVATE GitHub repo "
                         "(via GITHUB_TOKEN / --github-token) and use it as origin, then push. "
                         "No-op if 'origin' already exists. Requires --push.")
    ap.add_argument("--remote-name", default=None,
                    help="name for the auto-created GitHub repo (default: the repo folder's name)")
    ap.add_argument("--project-label", default=None,
                    help="human-readable project label (e.g. a Chinese client name) to set as the "
                         "new repo's description — this is what check_remote_exists.py's fuzzy "
                         "match later searches when the repo name itself doesn't match what the "
                         "user calls the project")
    ap.add_argument("--github-org", default=os.environ.get("GITHUB_ORG"),
                    help="create the repo under this GitHub Organization instead of the token "
                         "owner's personal account (or set GITHUB_ORG) — only used with --create-remote")
    ap.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"),
                    help="GitHub personal access token with repo-creation scope "
                         "(or set GITHUB_TOKEN) — only used with --create-remote")
    ap.add_argument("--no-changelog", action="store_true",
                    help="skip auto-appending a CHANGELOG.md entry for this commit")
    args = ap.parse_args(argv)

    src = Path(args.file).resolve()
    if not src.is_file():
        print(f"file not found: {src}", file=sys.stderr)
        return 4
    if src.suffix.lower() not in (".bot", ".flow"):
        print(f"unsupported file type {src.suffix!r} — expected .bot or .flow", file=sys.stderr)
        return 4

    repo_dir = Path(args.repo_dir).resolve() if args.repo_dir else src.parent
    ensure_repo(repo_dir)

    dest = repo_dir / src.name
    if dest.resolve() != src.resolve():
        shutil.copy2(src, dest)

    name, kind = bot_summary(dest)
    run(["git", "add", dest.name], cwd=repo_dir)

    # Use --no-textconv here: the textconv driver strips exportTime for *display*
    # purposes only. Change DETECTION must look at real bytes, otherwise a
    # content-identical re-export (only exportTime differs) would silently never
    # get committed, and a --version tag for it would have nothing to attach to.
    unchanged = subprocess.run(["git", "diff", "--cached", "--quiet", "--no-textconv"],
                                cwd=str(repo_dir)).returncode == 0
    message = args.message or f"Update {name}"
    if kind:
        message = f"[{kind}] {message}"

    if unchanged:
        print(f"no byte-level changes to archive for {dest.name} (identical to last commit)")
        commit_hash = run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, check=False)
    else:
        has_parent = run(["git", "rev-parse", "HEAD^"], cwd=repo_dir, check=False) != ""
        run(["git", "commit", "-m", message], cwd=repo_dir)
        commit_hash = run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir)
        print(f"committed {commit_hash}: {message}")

    if args.version:
        tag = f"altabots-v{args.version}"
        existing_tags = run(["git", "tag", "--list", tag], cwd=repo_dir, check=False)
        if existing_tags:
            print(f"tag {tag} already exists -> skipping (was: {existing_tags})")
        else:
            run(["git", "tag", tag], cwd=repo_dir)
            print(f"tagged {tag} -> {commit_hash}")

    if not unchanged and not args.no_changelog:
        author = run(["git", "config", "user.name"], cwd=repo_dir, check=False) or "unknown"
        write_changelog(repo_dir, dest, args.version, message, author, has_parent)

    if args.push:
        remotes = run(["git", "remote"], cwd=repo_dir, check=False).split()
        if "origin" not in remotes and args.create_remote:
            if not args.github_token:
                print("--create-remote needs a GitHub token: set GITHUB_TOKEN or pass --github-token",
                      file=sys.stderr)
                return 3
            remote_name = args.remote_name or repo_dir.name
            api_base = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
            ssh_url = create_github_repo(remote_name, args.github_token, private=True,
                                          org=args.github_org, description=args.project_label,
                                          api_base=api_base)
            run(["git", "remote", "add", "origin", ssh_url], cwd=repo_dir)
            owner = args.github_org or "your account"
            print(f"created private GitHub repo {remote_name!r} under {owner} -> {ssh_url}")
            remotes.append("origin")

        if "origin" in remotes:
            run(["git", "push", "origin", "HEAD"], cwd=repo_dir)
            run(["git", "push", "origin", "--tags"], cwd=repo_dir)
            print("pushed to origin")
        else:
            print("no 'origin' remote configured — commit saved locally only "
                  "(run `git remote add origin <url>` first, or pass --create-remote)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
