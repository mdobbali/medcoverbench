#!/usr/bin/env python3
"""Build the data file for the label-review tool.

Reads every data/pilot/<ncd>/ directory, the matching raw NCD and the policy's spec notes, and writes
one JSON file with the policy text, checklist criteria and cases the reviewer sees:
  {snapshot, priority, policies{ncd: {title, service, notes, url, sections}}, criteria{ncd: [...]},
   cases[{id, ncd, vignette, decision, violated, missing, note}]}

`priority` lists the cases every strong baseline missed (IMPLEMENTATION_LOG.md section 9), which are
the most likely label errors and the first ones reviewers should see.

Usage: python3 scripts/export_review_data.py [--out docs/review/data.json] [--snapshot-date YYYY-MM-DD]
Stdlib only, Python 3.9+.
"""
import argparse
import datetime
import json
import os

from export_hf import INDEX, MCD_URL, PILOT, ROOT, natural_key, raw_ncd

SECTIONS = [("Item/Service Description", "item_service_description"),
            ("Indications and Limitations of Coverage", "indications_limitations"),
            ("Reasons for Denial", "reasons_for_denial")]
PRIORITY = ["20.40-05", "210.2-01", "210.2-03", "210.2-06", "210.3-10", "280.14-02", "280.7-10"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "review", "data.json"))
    ap.add_argument("--snapshot-date", default=None)
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
                cases.append({"id": c["id"], "ncd": ncd, "vignette": c["vignette"],
                              "decision": c["gold"]["decision"],
                              "violated": c["gold"]["violated_criteria"],
                              "missing": c["gold"]["missing_documentation"],
                              "note": c.get("rationale_note", "")})
    cases.sort(key=lambda c: natural_key(c["id"]))
    ids = {c["id"] for c in cases}
    missing = [p for p in PRIORITY if p not in ids]
    if missing:
        raise SystemExit("priority cases not in the dataset: %s" % ", ".join(missing))

    snapshot = args.snapshot_date or datetime.date.fromtimestamp(os.path.getmtime(INDEX)).isoformat()
    out = {"snapshot": snapshot, "priority": PRIORITY, "policies": policies, "criteria": criteria, "cases": cases}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote %s: %d policies, %d cases" % (args.out, len(policies), len(cases)))


if __name__ == "__main__":
    main()
