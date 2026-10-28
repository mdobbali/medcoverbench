#!/usr/bin/env python3
"""Score prediction files from run_eval.py against gold labels.

Metrics:
  accuracy, macro_f1          3-way decision
  unsafe_approval_rate        predicted "covered" when gold is not_covered/insufficient_documentation
  over_denial_rate            predicted not "covered" when gold is "covered"
  citation_recall             gold violated/missing criteria matched by at least one policy quote
                              (token overlap with the criterion's policy span >= 0.5)
  parse_failure_rate          replies with no valid JSON decision (counted as wrong)
  ncd_accuracy                long-context track only: the reply names the governing NCD

Usage: python3 scripts/score.py results/*.jsonl
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = ["covered", "not_covered", "insufficient_documentation"]


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def quote_matches(quote, span):
    """Share of the criterion span's tokens found in the quote."""
    span_t = tokens(span)
    return bool(span_t) and len(span_t & tokens(quote)) / len(span_t) >= 0.5


def load_gold():
    cases, spans = {}, {}
    for d in glob.glob(os.path.join(ROOT, "data", "pilot", "*")):
        checklist = json.load(open(os.path.join(d, "checklist.json")))
        spans[checklist["ncd"]] = {c["id"]: c["span"] for c in checklist["criteria"]}
        for line in open(os.path.join(d, "cases.jsonl")):
            if line.strip():
                c = json.loads(line)
                cases[c["id"]] = c
    return cases, spans


def score(path, cases, spans):
    preds = [json.loads(l) for l in open(path) if l.strip()]
    n = len(preds)
    conf = {(g, p): 0 for g in LABELS for p in LABELS + [None]}
    cite_hit = cite_total = 0
    ncd_hit = ncd_total = 0
    for row in preds:
        case = cases[row.get("case_id", row["id"])]
        gold = case["gold"]["decision"]
        pred = row["prediction"] or {}
        decision = pred.get("decision")
        conf[(gold, decision if decision in LABELS else None)] += 1
        if "case_id" in row:
            ncd_total += 1
            named = re.sub(r"^(NCD\s*)", "", str(pred.get("ncd", "")).strip(), flags=re.I)
            ncd_hit += named == case["ncd"]

        quotes = [q for q in pred.get("policy_quotes", []) if isinstance(q, str)]
        quotes += [q for q in pred.get("missing_documentation", []) if isinstance(q, str)]
        for cid in case["gold"]["violated_criteria"] + case["gold"]["missing_documentation"]:
            cite_total += 1
            cite_hit += any(quote_matches(q, spans[case["ncd"]][cid]) for q in quotes)

    correct = sum(conf[(l, l)] for l in LABELS)
    f1s = []
    for l in LABELS:
        tp = conf[(l, l)]
        fp = sum(conf[(g, l)] for g in LABELS if g != l)
        fn = sum(conf[(l, p)] for p in LABELS + [None] if p != l)
        f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    negatives = sum(conf[(g, p)] for g in LABELS[1:] for p in LABELS + [None])
    positives = sum(conf[("covered", p)] for p in LABELS + [None])
    return {
        "file": os.path.basename(path), "n": n,
        "accuracy": correct / n if n else 0,
        "macro_f1": sum(f1s) / len(f1s),
        "unsafe_approval_rate": sum(conf[(g, "covered")] for g in LABELS[1:]) / negatives if negatives else 0,
        "over_denial_rate": sum(conf[("covered", p)] for p in LABELS[1:] + [None]) / positives if positives else 0,
        "citation_recall": cite_hit / cite_total if cite_total else 0,
        "parse_failure_rate": sum(conf[(g, None)] for g in LABELS) / n if n else 0,
        "ncd_accuracy": ncd_hit / ncd_total if ncd_total else float("nan"),
    }


def main():
    cases, spans = load_gold()
    rows = [score(p, cases, spans) for p in sys.argv[1:]]
    cols = ["n", "accuracy", "macro_f1", "unsafe_approval_rate", "over_denial_rate", "citation_recall",
            "parse_failure_rate"]
    if any(r["ncd_accuracy"] == r["ncd_accuracy"] for r in rows):
        cols.append("ncd_accuracy")
    print("%-32s" % "file" + "".join("%12s" % c[:11] for c in cols))
    for r in rows:
        print("%-32s" % r["file"][:31] + "".join(
            "%12d" % r[c] if c == "n" else "%12.3f" % r[c] for c in cols))


if __name__ == "__main__":
    main()
