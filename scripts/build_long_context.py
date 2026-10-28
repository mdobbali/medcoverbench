#!/usr/bin/env python3
"""Build the long-context track: each case's NCD hidden in a library of other real NCDs.

The model is not told which policy applies. It gets a library of NCDs and the case, and must find the
governing NCD and then decide coverage as in the single-policy track. Items store only the library's
NCD ids in order; run_eval.py assembles the text from data/raw/ncd/ at run time.

Design (all deterministic from --seed):
  - Subset: --per-class cases per gold decision, spread round-robin across policies. The cases every
    strong baseline missed (likely label errors, see export_review_data.PRIORITY) are excluded.
  - Distractors: about half from the target's chapter (same number before the first dot, e.g. 20.x),
    the rest from other chapters, then shuffled. Excluded: the target's parent/child NCDs (20.9 vs
    20.9.1) and any NCD that cross-references the target or that the target cross-references, since
    those can bear on the same service.
  - Sizes are nested: the library for a smaller size is a subset of the next size's distractors, so a
    score change between sizes comes from length, not from a different set of distractors.
  - Depth: the target's relative position in the library cycles through 0, .25, .5, .75, 1.
  - Size is estimated as characters / 4. Actual token counts are in each run's usage field.

Usage: python3 scripts/build_long_context.py [--sizes 32000 96000] [--per-class 40] [--seed 7]
Writes data/long_context/items-<size/1000>k.jsonl. Stdlib only, Python 3.9+.
"""
import argparse
import glob
import json
import os
import random
import re

from export_hf import PILOT, RAW, ROOT, natural_key
from export_review_data import PRIORITY

FIELDS = ["item_service_description", "indications_limitations", "reasons_for_denial"]
LABELS = ["covered", "not_covered", "insufficient_documentation"]
DEPTHS = [0.0, 0.25, 0.5, 0.75, 1.0]
NCD_REF = re.compile(r"\b\d{2,3}\.\d+(?:\.\d+)?\b")


def load_ncds():
    """Latest version of every downloaded NCD, keyed by display id."""
    best = {}
    for p in glob.glob(os.path.join(RAW, "*_v*.json")):
        m = re.search(r"([^/]+)_v(\d+)\.json$", p)
        ncd, ver = m.group(1), int(m.group(2))
        if ncd not in best or ver > best[ncd][0]:
            best[ncd] = (ver, p)
    out = {}
    for ncd, (_, p) in best.items():
        with open(p) as f:
            doc = json.load(f)
        chars = sum(len(doc.get(k) or "") for k in FIELDS)
        if chars:
            out[ncd] = {"chars": chars + len(doc["title"]) + 40,
                        "refs": set(NCD_REF.findall(doc.get("cross_reference") or "")) - {ncd}}
    return out


def chapter(ncd):
    return ncd.split(".")[0]


def related(a, b, ncds):
    return (a.startswith(b + ".") or b.startswith(a + ".") or
            b in ncds[a]["refs"] or a in ncds[b]["refs"])


def pick_cases(per_class, rng):
    cases = []
    for d in sorted(glob.glob(os.path.join(PILOT, "*", "cases.jsonl"))):
        cases += [json.loads(l) for l in open(d) if l.strip()]
    chosen = []
    for label in LABELS:
        by_ncd = {}
        for c in cases:
            if c["gold"]["decision"] == label and c["id"] not in PRIORITY:
                by_ncd.setdefault(c["ncd"], []).append(c)
        for v in by_ncd.values():
            rng.shuffle(v)
        order = sorted(by_ncd, key=natural_key)
        rng.shuffle(order)
        picked = []
        while len(picked) < per_class and any(by_ncd.values()):
            for n in order:
                if by_ncd[n] and len(picked) < per_class:
                    picked.append(by_ncd[n].pop())
        chosen += picked
    return sorted(chosen, key=lambda c: natural_key(c["id"]))


def distractor_order(target, ncds, rng):
    """All eligible distractors, interleaving same-chapter and other-chapter NCDs."""
    pool = [n for n in sorted(ncds, key=natural_key) if n != target and not related(target, n, ncds)]
    near = [n for n in pool if chapter(n) == chapter(target)]
    far = [n for n in pool if chapter(n) != chapter(target)]
    rng.shuffle(near)
    rng.shuffle(far)
    out = []
    while near or far:
        if near:
            out.append(near.pop())
        if far:
            out.append(far.pop())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[32000, 96000])
    ap.add_argument("--per-class", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "long_context"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    ncds = load_ncds()
    cases = pick_cases(args.per_class, rng)
    sizes = sorted(args.sizes)
    rows = {s: [] for s in sizes}
    for i, case in enumerate(cases):
        target = case["ncd"]
        order = distractor_order(target, ncds, rng)
        depth = DEPTHS[i % len(DEPTHS)]
        for s in sizes:
            budget = s * 4 - ncds[target]["chars"]
            chosen, used = [], 0
            for n in order:
                if used >= budget:
                    break
                chosen.append(n)
                used += ncds[n]["chars"]
            # Shuffle so same-chapter policies aren't clustered; seeded per case for reproducibility.
            lib = sorted(chosen, key=natural_key)
            random.Random("%s-%s" % (args.seed, case["id"])).shuffle(lib)
            lib.insert(round(depth * len(lib)), target)
            est = sum(ncds[n]["chars"] for n in lib) // 4
            rows[s].append({"id": "%s@%dk" % (case["id"], s // 1000), "case_id": case["id"],
                            "size": s, "target_ncd": target, "depth": depth,
                            "library": lib, "est_tokens": est})

    os.makedirs(args.out, exist_ok=True)
    for s in sizes:
        path = os.path.join(args.out, "items-%dk.jsonl" % (s // 1000))
        with open(path, "w") as f:
            for r in rows[s]:
                f.write(json.dumps(r) + "\n")
        est = [r["est_tokens"] for r in rows[s]]
        print("%s: %d items, est tokens %d-%d, mean %d library size %.1f" % (
            path, len(est), min(est), max(est), sum(est) / len(est),
            sum(len(r["library"]) for r in rows[s]) / len(est)))


if __name__ == "__main__":
    main()
