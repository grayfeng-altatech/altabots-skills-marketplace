#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git textconv helper for .bot/.flow files.

Registered via .gitattributes (`*.bot diff=altabots-json`) + a local
`git config diff.altabots-json.textconv "python3 .../clean_bot_diff.py"`.
git calls this with a file path and diffs the *output* instead of the raw
bytes, so `git diff` / `git log -p` show only real content changes instead
of noise from fields the platform regenerates on every export (e.g.
`exportTime`) or from key-order differences between exports.

The committed file on disk is untouched — this only affects what `git diff`
displays.
"""
import json
import sys

VOLATILE_KEYS = {"exportTime"}


def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


def main(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(json.dumps(clean(data), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
