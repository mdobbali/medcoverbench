#!/usr/bin/env python3
"""Break down long-context results: accuracy by target depth, and whether errors come from finding
the wrong NCD or from misapplying the right one.

For each results file from run_eval.py --items, prints:
  - decision accuracy overall, when the named NCD is right, and when it is wrong
  - NCD accuracy, and for wrong NCDs, the share from the target's own chapter
  - decision accuracy at each target depth (0 = first policy in the library, 1 = last)
  - 95% bootstrap confidence intervals for accuracy and unsafe approval rate

Usage: python3 scripts/long_context_report.py results/long_context/*.jsonl
"""
import glob
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load():
    gold, items = {}, {}
    for p in glob.glob(os.path.join(ROOT, "data", "pilot", "*", "cases.jsonl")):
        for line in open(p):
            if line.strip():
                c = json.loads(line)
                gold[c["id"]] = c
    for p in glob.glob(os.path.join(ROOT, "data", "long_context", "items-*.jsonl")):
        for line in open(p):
            if line.strip():
                it = json.loads(line)
                items[it["id"]] = it
    return gold, items


def bootstrap_ci(values, reps=2000, seed=0):
    """95% percentile interval for the mean of 0/1 values."""
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def pct(a, b):
    return "%5.1f%% (%d/%d)" % (100.0 * a / b, a, b) if b else "    -"


def main():
    gold, items = load()
    for path in sys.argv[1:]:
        rows = [json.loads(l) for l in open(path) if l.strip()]
        right_ncd = wrong_ncd = right_ncd_ok = wrong_ncd_ok = same_chapter = 0
        by_depth = {}
        tokens = []
        correct, unsafe = [], []
        for r in rows:
            it = items[r["id"]]
            case = gold[it["case_id"]]
            pred = r["prediction"] or {}
            ok = pred.get("decision") == case["gold"]["decision"]
            correct.append(int(ok))
            if case["gold"]["decision"] != "covered":
                unsafe.append(int(pred.get("decision") == "covered"))
            named = re.sub(r"^NCD\s*", "", str(pred.get("ncd", "")).strip(), flags=re.I)
            if named == it["target_ncd"]:
                right_ncd += 1
                right_ncd_ok += ok
            else:
                wrong_ncd += 1
                wrong_ncd_ok += ok
                same_chapter += named.split(".")[0] == it["target_ncd"].split(".")[0]
            d = by_depth.setdefault(it["depth"], [0, 0])
            d[0] += ok
            d[1] += 1
            if r.get("usage", {}).get("prompt_tokens"):
                tokens.append(r["usage"]["prompt_tokens"])
        n = len(rows)
        print("== %s  (n=%d, mean prompt tokens %s)" % (
            os.path.basename(path), n, "%d" % (sum(tokens) / len(tokens)) if tokens else "?"))
        print("  accuracy                 %s  95%% CI %.3f-%.3f" % (
            (pct(right_ncd_ok + wrong_ncd_ok, n),) + bootstrap_ci(correct)))
        print("  unsafe approval          %s  95%% CI %.3f-%.3f" % (
            (pct(sum(unsafe), len(unsafe)),) + bootstrap_ci(unsafe)))
        print("  NCD accuracy             %s" % pct(right_ncd, n))
        print("  accuracy | right NCD     %s" % pct(right_ncd_ok, right_ncd))
        print("  accuracy | wrong NCD     %s" % pct(wrong_ncd_ok, wrong_ncd))
        print("  wrong NCD, same chapter  %s" % pct(same_chapter, wrong_ncd))
        print("  accuracy by depth        " + "  ".join(
            "%.2f: %d/%d" % (k, v[0], v[1]) for k, v in sorted(by_depth.items())))


if __name__ == "__main__":
    main()
