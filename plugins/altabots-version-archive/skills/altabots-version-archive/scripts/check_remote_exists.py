#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check whether a GitHub repo matching a given name already exists — the
"look before you act" step that must run BEFORE archive_to_git.py
--create-remote, so the invoking skill can ask the user to confirm what's
about to happen instead of silently creating a duplicate or pushing into
the wrong place.

Two passes:
  1. Exact lookup (GET /repos/{owner}/{name}).
  2. If that 404s, list every repo the owner/org has and FUZZY-match the
     query against each repo's name AND description (substring, either
     direction, case-insensitive; plus a difflib similarity ratio on the
     name alone for typo-level closeness). This exists because the
     project's real repo may not be a literal string match — e.g. the user
     asks for "陽明海運" but the repo is actually named `yangming-agent`
     with "陽明海運" only in its description, or named slightly differently
     than expected. Only a substring/description hit crosses a Chinese
     name <-> English slug gap; the difflib ratio alone won't (it compares
     characters, not translations) — this is a real limit, not something
     any string algorithm fixes, which is why setting a `description` when
     you create a repo (see archive_to_git.py's --project-label) matters.

This script only READS; it never creates, modifies, or pushes anything.
Confirming with the user and then deciding which archive_to_git.py flags to
run is the invoking skill's job, not this script's.

Usage:
  python3 check_remote_exists.py <name> [--github-org ORG] [--github-token TOKEN]

Prints and exits:
  FOUND <ssh_url>              exit 0  — exact name match exists
  CANDIDATES\\n<repo>\\t<ssh_url>\\t<description>\\n...
                                exit 2  — no exact match, but similar repos
                                          found — ask the user which (if any)
  NOT_FOUND                     exit 1  — nothing exact or similar found
  (error message)               exit 3  — couldn't tell (bad/missing token, ...)
"""
import argparse
import difflib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FUZZY_RATIO_THRESHOLD = 0.6


def api_get(path, token, api_base):
    req = urllib.request.Request(f"{api_base}{path}",
                                  headers={"Authorization": f"Bearer {token}",
                                           "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def owner_login(token, api_base):
    return api_get("/user", token, api_base)["login"]


def list_all_repos(owner, org, token, api_base):
    """Up to 300 repos (3 pages of 100) — enough for any team's actual repo
    count; a hard cap rather than unbounded pagination so a runaway org
    can't make this hang."""
    path_base = f"/orgs/{org}/repos" if org else "/user/repos"
    repos = []
    for page in (1, 2, 3):
        batch = api_get(f"{path_base}?per_page=100&page={page}", token, api_base)
        repos.extend(batch)
        if len(batch) < 100:
            break
    return repos


def fuzzy_candidates(query, repos):
    q = query.lower()
    scored = []
    for repo in repos:
        name = (repo.get("name") or "")
        desc = (repo.get("description") or "")
        name_l, desc_l = name.lower(), desc.lower()
        substring_hit = q in name_l or q in desc_l or name_l in q
        ratio = difflib.SequenceMatcher(None, q, name_l).ratio()
        if substring_hit or ratio >= FUZZY_RATIO_THRESHOLD:
            scored.append((max(ratio, 1.0 if substring_hit else 0.0), repo))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [repo for _, repo in scored[:5]]


def main(argv):
    ap = argparse.ArgumentParser(description="Check whether a matching GitHub repo already exists, before creating one")
    ap.add_argument("name", help="the repo name / project label to check for")
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

    try:
        # The exact-lookup name almost always fails this check anyway (a
        # Chinese project label was never going to BE the repo's literal
        # slug), but it must not CRASH — non-ASCII in a URL path raises
        # UnicodeEncodeError deep in urllib unless percent-encoded first.
        data = api_get(f"/repos/{owner}/{urllib.parse.quote(args.name, safe='')}", args.github_token, api_base)
        print(f"FOUND {data['ssh_url']}")
        return 0
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"GitHub API error checking {owner}/{args.name}: HTTP {e.code}", file=sys.stderr)
            return 3
    except urllib.error.URLError as e:
        print(f"network error calling GitHub API: {e}", file=sys.stderr)
        return 3

    # no exact match — widen the search across everything the owner/org has
    try:
        repos = list_all_repos(owner, args.github_org, args.github_token, api_base)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"could not list repos to fuzzy-match against: {e}", file=sys.stderr)
        return 3

    candidates = fuzzy_candidates(args.name, repos)
    if candidates:
        print("CANDIDATES")
        for repo in candidates:
            print(f"{repo['full_name']}\t{repo['ssh_url']}\t{repo.get('description') or ''}")
        return 2

    print(f"NOT_FOUND (would be created as {owner}/{args.name})")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
