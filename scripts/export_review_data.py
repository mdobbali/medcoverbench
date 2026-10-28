#!/usr/bin/env python3
"""Build the data file for the label-review tool.

Reads every data/pilot/<ncd>/ directory, the matching raw NCD and the policy's spec notes, and writes
one JSON file with the policy text, checklist criteria and cases the reviewer sees:
  {snapshot, priority, assignment, policies{ncd: {title, service, notes, url, sections}},
   criteria{ncd: [...]}, cases[{id, service, ncd, vignette, decision, violated, missing, note}]}

`priority` lists the seven cases every strong baseline missed in the first run (IMPLEMENTATION_LOG.md
section 9a). The long-context sample excludes them, so this list stays fixed.

`assignment` is the set every reviewer is asked to review, the same for all of them so their
agreement can be measured: the cases still missed by all four strongest models after the case
revision (section 9d), then two cases from each of the 50 policies, chosen with --seed and with
different decisions where the policy allows. Changing the seed changes the assignment; don't change
it once reviews have started.

Usage: python3 scripts/export_review_data.py [--out docs/review/data.json] [--snapshot-date YYYY-MM-DD]
Stdlib only, Python 3.9+.
"""
import argparse
import datetime
import json
import os
import random

from export_hf import INDEX, MCD_URL, PILOT, ROOT, natural_key, raw_ncd

SECTIONS = [("Item/Service Description", "item_service_description"),
            ("Indications and Limitations of Coverage", "indications_limitations"),
            ("Reasons for Denial", "reasons_for_denial")]
PRIORITY = ["20.40-05", "210.2-01", "210.2-03", "210.2-06", "210.3-10", "280.14-02", "280.7-10"]
UNRESOLVED = ["20.40-05", "280.14-02"]


def assignment(cases, seed):
    """UNRESOLVED first, then two cases per policy, preferring two different decisions."""
    rng = random.Random(seed)
    by_ncd = {}
    for c in cases:
        if c["id"] not in UNRESOLVED:
            by_ncd.setdefault(c["ncd"], []).append(c)
    picked = []
    for ncd in sorted(by_ncd, key=natural_key):
        pool = sorted(by_ncd[ncd], key=lambda c: natural_key(c["id"]))
        rng.shuffle(pool)
        first = pool[0]
        second = next((c for c in pool[1:] if c["decision"] != first["decision"]), pool[1])
        picked += [first["id"], second["id"]]
    return UNRESOLVED + sorted(picked, key=natural_key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "review", "data.json"))
    ap.add_argument("--snapshot-date", default=None)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    policies, criteria, cases = {}, {}, []
    for ncd in sorted(os.listdir(PILOT), key=natural_key):
        d = os.path.join(PILOT, ncd)
        if not os.path.isfile(os.path.join(d, "checklist.json")):
            continue
        with open(os.path.join(d, "checklist.json")) as f:
            chk = json.load(f)
        doc = raw_ncd(ncd)
        # Hand-written policies keep their notes in the checklist; the rest in the spec.
        spec_path = os.path.join(ROOT, "data", "specs", ncd + ".json")
        notes = chk.get("notes", "")
        if not notes and os.path.isfile(spec_path):
            with open(spec_path) as f:
                notes = json.load(f).get("notes", "")
        policies[ncd] = {
            "title": chk["title"],
            "service": chk["service"],
            "notes": notes,
            "url": MCD_URL % (doc["document_id"], doc["document_version"]),
            "sections": [[label, doc[key]] for label, key in SECTIONS if doc.get(key)],
        }
        criteria[ncd] = [{"id": c["id"], "text": c["text"], "span": c["span"], "type": c.get("type", "")}
                         for c in chk["criteria"]]
        with open(os.path.join(d, "cases.jsonl")) as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                cases.append({"id": c["id"], "ncd": ncd, "service": c["service"], "vignette": c["vignette"],
                              "decision": c["gold"]["decision"],
                              "violated": c["gold"]["violated_criteria"],
                              "missing": c["gold"]["missing_documentation"],
                              "note": c.get("rationale_note", "")})
    cases.sort(key=lambda c: natural_key(c["id"]))
    ids = {c["id"] for c in cases}
    missing = [p for p in PRIORITY + UNRESOLVED if p not in ids]
    if missing:
        raise SystemExit("priority cases not in the dataset: %s" % ", ".join(missing))

    snapshot = args.snapshot_date or datetime.date.fromtimestamp(os.path.getmtime(INDEX)).isoformat()
    out = {"snapshot": snapshot, "priority": PRIORITY, "assignment": assignment(cases, args.seed),
           "policies": policies, "criteria": criteria, "cases": cases}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote %s: %d policies, %d cases, %d assigned" % (
        args.out, len(policies), len(cases), len(out["assignment"])))


if __name__ == "__main__":
    main()
