#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check whether a GitHub repo with a given name already exists — the "look
before you act" step that must run BEFORE archive_to_git.py --create-remote,
so the invoking skill can ask the user to confirm what's about to happen
instead of silently creating a duplicate or pushing into the wrong place.

This script only READS (GET /repos/{owner}/{name}); it never creates,
modifies, or pushes anything. Confirming with the user and then deciding
which archive_to_git.py flags to run is the invoking skill's job, not this
script's — this only answers "does it exist, and if so what's its URL".

Usage:
  python3 check_remote_exists.py <name> [--github-org ORG] [--github-token TOKEN]

Prints one line and exits:
  FOUND <ssh_url>   exit 0  — a repo with this name already exists there
  NOT_FOUND         exit 1  — no repo with this name exists there yet
  (error message)   exit 3  — couldn't tell (bad/missing token, network error, ...)
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def owner_login(token, api_base):
    req = urllib.request.Request(f"{api_base}/user",
                                  headers={"Authorization": f"Bearer {token}",
                                           "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["login"]


def main(argv):
    ap = argparse.ArgumentParser(description="Check whether a GitHub repo already exists, before creating one")
    ap.add_argument("name", help="the repo name to check for")
    ap.add_argument("--github-org", default=os.environ.get("GITHUB_ORG"),
                    help="check under this GitHub Organization instead of the token owner's personal account")
    ap.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"),
                    help="GitHub personal access token (or set GITHUB_TOKEN)")
    args = ap.parse_args(argv)

    if not args.github_token:
        print("no GitHub token available: set GITHUB_TOKEN or pass --github-token", file=sys.stderr)
        return 3

    api_base = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

    try:
        owner = args.github_org or owner_login(args.github_token, api_base)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"could not resolve account/org: {e}", file=sys.stderr)
        return 3

    req = urllib.request.Request(
        f"{api_base}/repos/{owner}/{args.name}",
        headers={"Authorization": f"Bearer {args.github_token}",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        print(f"FOUND {data['ssh_url']}")
        return 0
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"NOT_FOUND (would be created as {owner}/{args.name})")
            return 1
        print(f"GitHub API error checking {owner}/{args.name}: HTTP {e.code}", file=sys.stderr)
        return 3
    except urllib.error.URLError as e:
        print(f"network error calling GitHub API: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
