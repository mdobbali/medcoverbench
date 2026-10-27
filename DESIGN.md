# Medicare Coverage Reasoning Benchmark: design (draft v0.1, 2026-10-24)

## Goal
Measure whether LLMs can decide Medicare coverage from the **real, full-length CMS policy text**:
apply the criteria correctly, cite the governing section, and recognize when documentation is missing.

Gap it fills: χ-Bench (2026) uses a synthetic managed-care handbook, and other prior-auth work uses
small, unreleased chunk corpora. No public benchmark uses real CMS coverage policy at scale.

## Task
Each item gives:
- **Policy context:** the full NCD text (indications, limitations, non-covered uses), optionally
  with distractor NCDs added for a long-context setting
- **Case:** a synthetic clinical vignette (age, diagnosis, history, prior treatments, the requested
  service and the documentation available)

The model returns JSON:
```json
{"decision": "covered | not_covered | insufficient_documentation",
 "criteria_cited": ["<verbatim or section-anchored policy span>", "..."],
 "missing_documentation": ["..."],
 "rationale": "..."}
```

## Case construction (per NCD)
1. Extract the coverage criteria as an explicit checklist from `indications_limitations`
   (an LLM drafts it, a human verifies it).
2. Generate vignettes by controlled perturbation, so the gold label follows from the checklist:
   - all criteria met → covered
   - one criterion violated → not covered (the violated criterion is the gold citation)
   - one criterion's evidence absent → insufficient documentation
   - near-miss and distractor details (e.g., a similar but non-qualifying diagnosis)
3. Expert review: a clinician or certified coder checks a sample of labels (100% for the pilot).

Vignettes are synthetic, so no PHI is involved.

## Splits and scale
- **Pilot:** 10 NCDs × 5 cases = 50 items, fully expert-reviewed
- **v1.0:** about 60 NCDs × 8 cases ≈ 500 items; a public dev set plus a held-out test set
  (labels kept private, scored through the leaderboard to limit contamination)
- **Long-context track:** the target NCD buried among 10–50 other NCDs (32k–200k tokens)

## Metrics
- Decision accuracy and macro-F1 over the 3 classes
- Citation precision and recall against the gold criteria (span overlap)
- Missing-documentation recall
- **Unsafe-approval rate:** predicted covered when the gold label is not covered or
  insufficient documentation. This is the headline safety number.
- Accuracy against context length (long-context track)

## Licensing
- NCD text is a US government work, so it is redistributable.
- **LCDs and billing articles contain AMA CPT content**, so we never redistribute them. LCD items,
  if added later, ship as IDs plus a loader script that users run after accepting the CMS/AMA license.
- Use ICD-10-CM (public domain) and HCPCS Level II. Avoid CPT descriptors in vignettes.
- Benchmark license: CC BY 4.0 for data, Apache 2.0 for code.

## Baselines
Open models (Qwen, Llama, Mistral, Gemma families, at several sizes) via vLLM, plus 2–3 frontier
APIs. Later, the author's long-context domain-adapted models are evaluated on the same harness.

## Release
HF dataset with a dataset card and BibTeX, a GitHub repo for the harness, an arXiv paper, and an
HF Space leaderboard. Each release is added to `oss/tracker/config.json`.

## Open decisions
- Expert reviewers (needed before the pilot labels are final)
- Name (working title: **MedCoverBench**; check that it is free on HF/GitHub/arXiv)
