#!/usr/bin/env python3
"""Rank downloaded NCDs by how well they suit criteria-based case generation.

Prefers policies with explicit, checkable conditions ("only if", "must", numbered criteria)
and excludes ones that are blanket non-coverage or left to contractor discretion.
Prints a TSV shortlist to stdout.
"""
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONDITION = re.compile(r"\b(only if|only when|must|provided that|criteria|at least|following conditions|"
                       r"documented|documentation|in the absence of|is covered (for|when|if))\b", re.I)
DISCRETION = re.compile(r"local (contractor|MAC)s? (discretion|may determine)|at the discretion of", re.I)
BLANKET_NC = re.compile(r"nationally non-?covered|is not covered under Medicare|no coverage", re.I)


def main():
    rows = []
    for path in glob.glob(os.path.join(ROOT, "data", "raw", "ncd", "*.json")):
        d = json.load(open(path))
        text = d.get("indications_limitations", "")
        n = len(text)
        if not 1500 <= n <= 20000:
            continue
        conds = len(CONDITION.findall(text))
        bullets = len(re.findall(r"^\s*(-|\d+\.|[a-z]\.)\s", text, re.M))
        discretion = len(DISCRETION.findall(text))
        blanket = len(BLANKET_NC.findall(text[:600]))
        score = conds * 2 + min(bullets, 15) - discretion * 5 - blanket * 8
        rows.append((score, d["document_display_id"], d["title"], n, conds, bullets, discretion))
    rows.sort(reverse=True)
    print("score\tncd\tchars\tconds\tbullets\tdiscretion\ttitle")
    for score, ncd, title, n, conds, bullets, disc in rows[:40]:
        print("%d\t%s\t%d\t%d\t%d\t%d\t%s" % (score, ncd, n, conds, bullets, disc, title[:70]))


if __name__ == "__main__":
    main()
