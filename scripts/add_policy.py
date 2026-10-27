#!/usr/bin/env python3
"""Write a pilot policy's checklist.json and cases.jsonl from one spec file, with validation.

Spec format (JSON):
  {"ncd": "20.34", "service": "...", "notes": "...",
   "criteria": [{"id": "C1", "text": "...", "span": "<verbatim from the NCD>", "type": "..."}],
   "cases": [{"decision": "...", "violated": ["C2"], "missing": [], "note": "...", "vignette": "..."}]}

Checks every span appears verbatim in the downloaded NCD (whitespace-normalized) and every
gold criterion id exists, so a typo cannot silently break citation scoring.
Usage: python3 scripts/add_policy.py spec.json
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECISIONS = {"covered", "not_covered", "insufficient_documentation"}


def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[\s\-]+", " ", s).strip().lower()


def main():
    spec = json.load(open(sys.argv[1]))
    ncd = spec["ncd"]
    doc = json.load(open(sorted(glob.glob(os.path.join(ROOT, "data", "raw", "ncd", "%s_v*.json" % ncd)))[-1]))
    source = norm(" ".join(str(doc.get(k) or "") for k in
                           ("item_service_description", "indications_limitations", "reasons_for_denial")))

    errors = []
    ids = set()
    for c in spec["criteria"]:
        ids.add(c["id"])
        if norm(c["span"]) not in source:
            errors.append("%s span not found verbatim: %s" % (c["id"], c["span"][:80]))
    for i, case in enumerate(spec["cases"], 1):
        refs = case["violated"] + case["missing"]
        if case["decision"] not in DECISIONS:
            errors.append("case %d bad decision" % i)
        if not set(refs) <= ids:
            errors.append("case %d unknown criteria %s" % (i, set(refs) - ids))
        if (case["decision"] == "covered") != (not refs):
            errors.append("case %d: covered iff no violated/missing criteria" % i)
        if case["decision"] == "not_covered" and not case["violated"]:
            errors.append("case %d: not_covered needs a violated criterion" % i)
        if case["decision"] == "insufficient_documentation" and (case["violated"] or not case["missing"]):
            errors.append("case %d: insufficient_documentation needs only missing criteria" % i)
    if errors:
        sys.exit("\n".join(errors))

    out = os.path.join(ROOT, "data", "pilot", ncd)
    os.makedirs(out, exist_ok=True)
    checklist = {"ncd": ncd, "title": doc["title"], "service": spec["service"],
                 "review_status": "draft_unreviewed", "criteria": spec["criteria"]}
    if spec.get("notes"):
        checklist["notes"] = spec["notes"]
    json.dump(checklist, open(os.path.join(out, "checklist.json"), "w"), indent=1)
    with open(os.path.join(out, "cases.jsonl"), "w") as f:
        for i, c in enumerate(spec["cases"], 1):
            f.write(json.dumps({
                "id": "%s-%02d" % (ncd, i), "ncd": ncd, "service": spec["service"], "vignette": c["vignette"],
                "gold": {"decision": c["decision"], "violated_criteria": c["violated"],
                         "missing_documentation": c["missing"]},
                "rationale_note": c["note"], "review_status": "draft_unreviewed"}) + "\n")
    counts = {d: sum(c["decision"] == d for c in spec["cases"]) for d in sorted(DECISIONS)}
    print("%s: %d criteria, %d cases %s" % (ncd, len(spec["criteria"]), len(spec["cases"]), counts))


if __name__ == "__main__":
    main()
