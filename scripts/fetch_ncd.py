#!/usr/bin/env python3
"""Download all current National Coverage Determinations from the CMS Coverage API.

NCD text is a US government work and needs no license token (LCDs do: AMA CPT license).
Writes one JSON per NCD to data/raw/ncd/ with HTML fields converted to plain text,
plus data/raw/ncd_index.json, and keeps the original HTML under source_html.
Optional argument: output directory. Stdlib only; ~1 request/second.
"""
import html
import json
import os
import re
import sys
import time
import urllib.request

API = "https://api.coverage.cms.gov/v1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "raw", "ncd")
TEXT_FIELDS = ["item_service_description", "indications_limitations", "reasons_for_denial",
               "cross_reference", "other_text", "benefit_category"]


def get(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "medicare-bench-fetch"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * 2 ** attempt)


def to_text(value):
    """CMS returns HTML-escaped HTML; unescape, keep paragraph/list breaks, drop tags.

    Unescape once to get the markup, strip tags, then unescape the text. Unescaping twice first
    turns a literal "&amp;lt; 2.2" into a "<" that the tag regex then deletes through the next ">".
    """
    s = html.unescape(value or "")
    s = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/tr)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def main():
    os.makedirs(OUT, exist_ok=True)
    index = get(API + "/reports/national-coverage-ncd/")["data"]
    for i, row in enumerate(index, 1):
        path = os.path.join(OUT, "%s_v%s.json" % (row["document_display_id"], row["document_version"]))
        if os.path.exists(path):
            continue
        detail = get("%s/data/ncd/?ncdid=%s&ncdver=%s" % (API, row["document_id"], row["document_version"]))
        doc = detail["data"][0]
        doc["source_html"] = {f: doc.get(f) for f in TEXT_FIELDS}
        for f in TEXT_FIELDS:
            doc[f] = to_text(doc.get(f))
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=1)
        print("%3d/%d %s %s" % (i, len(index), row["document_display_id"], row["title"][:60]), flush=True)
        time.sleep(1)
    with open(os.path.join(os.path.dirname(OUT), "ncd_index.json"), "w") as fh:
        json.dump(index, fh, indent=1)


if __name__ == "__main__":
    sys.exit(main())
