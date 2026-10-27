#!/usr/bin/env python3
"""Export the benchmark to a Hugging Face dataset layout under release/hf/.

Reads every data/pilot/<ncd>/ directory present at run time (checklist.json + cases.jsonl) and the
matching raw NCD in data/raw/ncd/, then writes:
  release/hf/data/cases.jsonl     one row per case
  release/hf/data/policies.jsonl  one row per NCD used by at least one case
  release/hf/data/criteria.jsonl  one row per checklist criterion
  release/hf/README.md            rendered from release/hf/README.template.md ({{PLACEHOLDER}} values)

Output is deterministic: rows are sorted (NCD ids and case/criterion ids in natural order) and JSON
keys are written in a fixed order. Validation fails the run (exit 1) if a case references an NCD
with no policy row, a gold criterion id is not in that NCD's checklist, or a span is not verbatim in
the NCD text. Nothing is uploaded.

Usage: python3 scripts/export_hf.py [--out release/hf] [--snapshot-date YYYY-MM-DD]
Stdlib only, Python 3.9+.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOT = os.path.join(ROOT, "data", "pilot")
RAW = os.path.join(ROOT, "data", "raw", "ncd")
INDEX = os.path.join(ROOT, "data", "raw", "ncd_index.json")
LABELS = ["covered", "not_covered", "insufficient_documentation"]
# Public MCD page; pattern verified against ncdid=355&ncdver=2 (NCD 20.32), which returns HTTP 200.
MCD_URL = "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=%s&ncdver=%s"
DATE_FIELDS = ["effective_date", "effective_end_date", "implementation_date", "qr_modifier_date"]


def natural_key(s):
    """'20.4' < '20.32' < '20.40'; 'C2' < 'C10'; '20.32-02' < '20.32-10'."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.findall(r"\d+|[^\d]+", str(s))]


def norm(s):
    """Same normalization as scripts/add_policy.py."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[\s\-]+", " ", s).strip().lower()


def raw_ncd(ncd):
    """Latest downloaded version of an NCD (numeric version order)."""
    paths = glob.glob(os.path.join(RAW, "%s_v*.json" % ncd))
    if not paths:
        return None
    path = max(paths, key=lambda p: int(re.search(r"_v(\d+)\.json$", p).group(1)))
    with open(path) as f:
        return json.load(f)


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def size_category(n):
    for limit, label in [(1000, "n<1K"), (10000, "1K<n<10K"), (100000, "10K<n<100K")]:
        if n < limit:
            return label
    return "100K<n<1M"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "release", "hf"))
    ap.add_argument("--snapshot-date", default="",
                    help="date the raw NCDs were fetched (default: mtime of data/raw/ncd_index.json)")
    args = ap.parse_args()

    snapshot = args.snapshot_date or datetime.date.fromtimestamp(os.path.getmtime(INDEX)).isoformat()
    index = {}
    if os.path.exists(INDEX):
        with open(INDEX) as f:
            index = {r["document_display_id"]: r for r in json.load(f)}

    errors, warnings = [], []
    cases, criteria, checklists = [], [], {}
    for d in sorted(glob.glob(os.path.join(PILOT, "*")), key=lambda p: natural_key(os.path.basename(p))):
        cl_path, cs_path = os.path.join(d, "checklist.json"), os.path.join(d, "cases.jsonl")
        if not (os.path.isfile(cl_path) and os.path.isfile(cs_path)):
            warnings.append("skipping %s: missing checklist.json or cases.jsonl" % os.path.basename(d))
            continue
        with open(cl_path) as f:
            cl = json.load(f)
        ncd = cl["ncd"]
        if ncd != os.path.basename(d):
            errors.append("%s: checklist ncd %r does not match directory" % (d, ncd))
        checklists[ncd] = cl
        for c in cl["criteria"]:
            criteria.append({"ncd": ncd, "criterion_id": c["id"], "text": c["text"], "span": c["span"],
                             "type": c.get("type")})
        with open(cs_path) as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                g = c["gold"]
                cases.append({
                    "id": c["id"], "ncd": c["ncd"], "service": c["service"], "vignette": c["vignette"],
                    "gold_decision": g["decision"],
                    "gold_violated_criteria": list(g["violated_criteria"]),
                    "gold_missing_documentation": list(g["missing_documentation"]),
                    "rationale_note": c.get("rationale_note"),
                    "review_status": c.get("review_status")})

    # Policies: one row per NCD referenced by a case.
    policies, sources = [], {}
    for ncd in sorted({c["ncd"] for c in cases}, key=natural_key):
        doc = raw_ncd(ncd)
        if doc is None:
            continue  # reported by validation below
        sources[ncd] = norm(" ".join(str(doc.get(k) or "") for k in
                                     ("item_service_description", "indications_limitations", "reasons_for_denial")))
        row = {
            "ncd": ncd,
            "version": doc["document_version"],
            "document_id": doc["document_id"],
            "title": doc["title"],
            "item_service_description": doc.get("item_service_description") or "",
            "indications_limitations": doc.get("indications_limitations") or "",
            "reasons_for_denial": doc.get("reasons_for_denial") or "",
            "source_url": MCD_URL % (doc["document_id"], doc["document_version"]),
            "benefit_category": doc.get("benefit_category") or None,
            "publication_number": doc.get("publication_number") or None,
            "transmittal_number": doc.get("transmittal_number") or None,
            "transmittal_url": doc.get("transmittal_url") or None,
        }
        for k in DATE_FIELDS:
            if k in doc:
                row[k] = doc[k] or None
        row["last_updated"] = index.get(ncd, {}).get("last_updated")
        row["snapshot_date"] = snapshot
        policies.append(row)

    # Validation.
    policy_ids = {p["ncd"] for p in policies}
    crit_ids = {}
    for c in criteria:
        key = (c["ncd"], c["criterion_id"])
        if key in crit_ids:
            errors.append("duplicate criterion %s %s" % key)
        crit_ids[key] = c
        if c["ncd"] in sources and norm(c["span"]) not in sources[c["ncd"]]:
            errors.append("%s %s span not verbatim in NCD text" % key)
    seen = set()
    for c in cases:
        if c["id"] in seen:
            errors.append("duplicate case id %s" % c["id"])
        seen.add(c["id"])
        if c["ncd"] not in policy_ids:
            errors.append("case %s: no policy row for NCD %s (raw NCD missing?)" % (c["id"], c["ncd"]))
        if c["gold_decision"] not in LABELS:
            errors.append("case %s: bad decision %r" % (c["id"], c["gold_decision"]))
        for cid in c["gold_violated_criteria"] + c["gold_missing_documentation"]:
            if (c["ncd"], cid) not in crit_ids:
                errors.append("case %s: gold criterion %s not in checklist for %s" % (c["id"], cid, c["ncd"]))
    for w in warnings:
        print("warning: " + w, file=sys.stderr)
    if errors:
        print("\n".join("error: " + e for e in errors), file=sys.stderr)
        sys.exit(1)

    cases.sort(key=lambda r: natural_key(r["id"]))
    criteria.sort(key=lambda r: (natural_key(r["ncd"]), natural_key(r["criterion_id"])))
    data_dir = os.path.join(args.out, "data")
    os.makedirs(data_dir, exist_ok=True)
    write_jsonl(os.path.join(data_dir, "cases.jsonl"), cases)
    write_jsonl(os.path.join(data_dir, "policies.jsonl"), policies)
    write_jsonl(os.path.join(data_dir, "criteria.jsonl"), criteria)

    # Counts.
    by_decision = {l: sum(c["gold_decision"] == l for c in cases) for l in LABELS}
    by_status = {}
    for c in cases:
        by_status[c["review_status"]] = by_status.get(c["review_status"], 0) + 1
    by_type = {}
    for c in criteria:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    print("cases:    %d %s" % (len(cases), by_decision))
    print("policies: %d" % len(policies))
    print("criteria: %d %s" % (len(criteria), dict(sorted(by_type.items(), key=lambda kv: str(kv[0])))))
    print("review_status: %s" % by_status)
    print("snapshot_date: %s" % snapshot)

    # Dataset card.
    template = os.path.join(args.out, "README.template.md")
    if not os.path.exists(template):
        print("warning: %s not found; README.md not rendered" % template, file=sys.stderr)
        return
    n_cases_by_ncd = {}
    for c in cases:
        n_cases_by_ncd[c["ncd"]] = n_cases_by_ncd.get(c["ncd"], 0) + 1
    n_crit_by_ncd = {}
    for c in criteria:
        n_crit_by_ncd[c["ncd"]] = n_crit_by_ncd.get(c["ncd"], 0) + 1
    policy_table = "\n".join(
        "| [%s](%s) | %s | %d | %d | %d |" % (
            p["ncd"], p["source_url"], p["title"].replace("|", "\\|"), p["version"],
            n_crit_by_ncd.get(p["ncd"], 0), n_cases_by_ncd.get(p["ncd"], 0)) for p in policies)
    type_table = "\n".join("| `%s` | %d |" % (t, n) for t, n in sorted(by_type.items(), key=lambda kv: str(kv[0])))
    values = {
        "N_CASES": len(cases), "N_POLICIES": len(policies), "N_CRITERIA": len(criteria),
        "N_COVERED": by_decision["covered"], "N_NOT_COVERED": by_decision["not_covered"],
        "N_INSUFFICIENT": by_decision["insufficient_documentation"],
        "N_UNREVIEWED": by_status.get("draft_unreviewed", 0),
        "SIZE_CATEGORY": size_category(len(cases)), "SNAPSHOT_DATE": snapshot,
        "POLICY_TABLE": policy_table, "CRITERIA_TYPE_TABLE": type_table,
    }
    with open(template, encoding="utf-8") as f:
        text = f.read()
    for k, v in values.items():
        text = text.replace("{{%s}}" % k, str(v))
    left = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", text)))
    if left:
        sys.exit("error: unfilled placeholders in template: %s" % ", ".join(left))
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote %s" % os.path.relpath(os.path.join(args.out, "README.md"), ROOT))


if __name__ == "__main__":
    main()
