#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Restore a historical version's .bot/.flow content back out of a git repo
archived by archive_to_git.py — the reverse direction. Everything else in
this skill goes platform/build -> git; this is the only tool that goes
git -> (ready to re-publish to the) platform.

Usage:
  python3 restore_version.py <repo-dir> <ref> <filename> [-o output.bot]
  python3 restore_version.py ~/altabots-my-agent-project altabots-v1.0.3 my-agent.bot

<ref> is anything git resolves: a tag from archive_to_git.py
(altabots-v1.0.3), a commit hash, HEAD~2, a branch name, etc.

Does NOT call publish_altabots.py itself — extracting an old file is
read-only and safe to always do; re-publishing it live is a side-effectful
action (publish_altabots.py's own docs already say so: only pass --release
when the user has asked to go live). This script just gets you the file;
it prints the next command to run, it doesn't run it.

Exit codes: 0 ok; 3 ref/file not found in repo; 4 usage error.
"""
import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def main(argv):
    ap = argparse.ArgumentParser(description="Extract a historical .bot/.flow version out of a git archive")
    ap.add_argument("repo_dir", help="the git repo created by archive_to_git.py")
    ap.add_argument("ref", help="git ref to restore from (tag, commit hash, HEAD~N, branch, ...)")
    ap.add_argument("filename", help="the .bot/.flow filename as committed in the repo")
    ap.add_argument("-o", "--output", default=None,
                     help="output path (default: <stem>.<ref>.<ext> next to the cwd, to avoid "
                          "silently overwriting the current working copy)")
    args = ap.parse_args(argv)

    repo_dir = Path(args.repo_dir).resolve()
    if not repo_dir.is_dir():
        print(f"not a directory: {repo_dir}", file=sys.stderr)
        return 4

    check = run(["git", "rev-parse", "--is-inside-work-tree"], repo_dir)
    if check.returncode != 0 or check.stdout.strip() != "true":
        print(f"not a git repo: {repo_dir}", file=sys.stderr)
        return 4

    resolved = run(["git", "rev-parse", "--short", args.ref], repo_dir)
    if resolved.returncode != 0:
        print(f"ref not found: {args.ref}", file=sys.stderr)
        return 3

    show = run(["git", "show", f"{args.ref}:{args.filename}"], repo_dir)
    if show.returncode != 0:
        print(f"'{args.filename}' does not exist at {args.ref} (typo, or wrong repo?)", file=sys.stderr)
        print(show.stderr.strip(), file=sys.stderr)
        return 3

    src = Path(args.filename)
    if args.output:
        out = Path(args.output).resolve()
    else:
        safe_ref = args.ref.replace("/", "_")
        out = Path.cwd() / f"{src.stem}.{safe_ref}{src.suffix}"

    out.write_text(show.stdout, encoding="utf-8")
    commit = resolved.stdout.strip()
    print(f"restored {args.filename} @ {args.ref} ({commit}) -> {out}")
    print("")
    print("This is a READ-ONLY extraction — nothing was published. To actually put it back")
    print("live on the platform (a side-effectful action — only do this if that's what you want):")
    print(f"  python3 publish_altabots.py {out} --api-key <KEY> --release "
          f'--version-desc "restored from {args.ref}"')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
