---
license: cc-by-4.0
language:
- en
task_categories:
- text-classification
- question-answering
tags:
- medical
- healthcare
- medicare
- benchmark
- long-context
- policy-reasoning
size_categories:
- {{SIZE_CATEGORY}}
pretty_name: MedCoverBench
configs:
- config_name: cases
  default: true
  data_files:
  - split: test
    path: data/cases.jsonl
- config_name: policies
  data_files:
  - split: test
    path: data/policies.jsonl
- config_name: criteria
  data_files:
  - split: test
    path: data/criteria.jsonl
---

# MedCoverBench

> **Status: pre-release draft.** Every label in this release has `review_status = "draft_unreviewed"`.
> Clinician / certified-coder review is pending. Do not treat the gold labels as expert-validated yet.

## Summary

MedCoverBench tests whether large language models can decide **Medicare coverage** from the
**real, full-length text of CMS National Coverage Determinations (NCDs)**. Each item pairs a
synthetic clinical vignette with the NCD that governs the requested service. The model must decide
whether the service is covered, quote the policy language that determines its decision, and list
any required documentation that is missing.

This release contains **{{N_CASES}} cases** over **{{N_POLICIES}} NCDs**, backed by
**{{N_CRITERIA}} policy criteria** whose spans are taken verbatim from the NCD text.

| Gold decision | Cases |
|---|---|
| `covered` | {{N_COVERED}} |
| `not_covered` | {{N_NOT_COVERED}} |
| `insufficient_documentation` | {{N_INSUFFICIENT}} |

NCD text snapshot date: **{{SNAPSHOT_DATE}}**.

## Motivation

Coverage and prior-authorization decisions are a common target for LLM automation, and mistakes
are costly in both directions: wrongly approving a service that policy does not cover, or wrongly
denying a patient a service that it does. Existing evaluations tend to use synthetic policy
handbooks or small, unreleased corpora of policy excerpts. MedCoverBench uses the actual public
Medicare national coverage policies, as published, so models have to read real regulatory prose
with its cross-references, exceptions and documentation requirements. It also separates "the facts
fail a criterion" from "the documentation needed to show a criterion is missing", a distinction
that matters in real coverage review.

## Task definition

**Input.** For each case, the model receives:

1. The policy: the NCD number and title, followed by the NCD's *Item/Service Description*,
   *Indications and Limitations of Coverage*, and (when present) *Reasons for Denial* sections,
   taken from `policies.jsonl`.
2. The case: the requested service (`service`) and a synthetic clinical vignette (`vignette`)
   describing the patient, history, prior treatment, setting and available documentation.

**Output.** A single JSON object:

```json
{"decision": "covered" | "not_covered" | "insufficient_documentation",
 "policy_quotes": ["verbatim text from the policy for each criterion that determines the decision"],
 "missing_documentation": ["each required item absent from the case"],
 "rationale": "2-4 sentences"}
```

**Decisions** (as defined in the reference harness's system prompt):

- `covered`: every applicable coverage criterion is met and documented.
- `not_covered`: the facts show at least one applicable criterion is not met.
- `insufficient_documentation`: no criterion is shown to be violated, but documentation required
  by the policy is missing.

The model is instructed to use only the provided policy and the case facts.

## Dataset structure

Three configs, each with a single split named `test`.

```python
from datasets import load_dataset
cases = load_dataset("<hf-user>/MedCoverBench", "cases", split="test")
policies = load_dataset("<hf-user>/MedCoverBench", "policies", split="test")
criteria = load_dataset("<hf-user>/MedCoverBench", "criteria", split="test")
```

Join `cases.ncd` to `policies.ncd` to build the prompt, and `(cases.ncd, gold criterion id)` to
`(criteria.ncd, criteria.criterion_id)` to recover the gold policy spans.

### `cases` ({{N_CASES}} rows)

| Field | Type | Description |
|---|---|---|
| `id` | string | Case id, `<ncd>-<nn>` |
| `ncd` | string | NCD display id (e.g. `20.32`); key into `policies` |
| `service` | string | The requested item or service |
| `vignette` | string | Synthetic clinical vignette (no real patient data) |
| `gold_decision` | string | `covered`, `not_covered` or `insufficient_documentation` |
| `gold_violated_criteria` | list[string] | Criterion ids the facts fail (non-empty iff `not_covered`) |
| `gold_missing_documentation` | list[string] | Criterion ids whose required evidence is absent (non-empty iff `insufficient_documentation`) |
| `rationale_note` | string | Short annotator note explaining the gold label |
| `review_status` | string | Label review state; currently `draft_unreviewed` for all rows |

### `policies` ({{N_POLICIES}} rows)

| Field | Type | Description |
|---|---|---|
| `ncd` | string | NCD display id |
| `version` | int | NCD document version in the snapshot |
| `document_id` | string | CMS Medicare Coverage Database document id (`ncdid`) |
| `title` | string | NCD title |
| `item_service_description` | string | "Item/Service Description" section, HTML converted to plain text |
| `indications_limitations` | string | "Indications and Limitations of Coverage" section, plain text |
| `reasons_for_denial` | string | "Reasons for Denial" section, plain text (often empty) |
| `source_url` | string | Public CMS Medicare Coverage Database page for this NCD version |
| `benefit_category` | string | Medicare benefit category |
| `publication_number` | string | CMS manual publication number (`100-3`, the NCD Manual) |
| `transmittal_number` | string | CMS transmittal number for this version, if any |
| `transmittal_url` | string | Link to the CMS transmittal, if any |
| `effective_date` | string | Effective date of this version (MM/DD/YYYY, as published by CMS) |
| `effective_end_date` | string | End date of this version (`N/A` if current) |
| `implementation_date` | string | Implementation date (MM/DD/YYYY) |
| `qr_modifier_date` | string | CMS quarterly-release modifier date, if any (often null) |
| `last_updated` | string | "Last updated" date from the CMS NCD index at snapshot time |
| `snapshot_date` | string | Date (YYYY-MM-DD) the NCD text was downloaded from the CMS Coverage API |

Policies in this release:

| NCD | Title | Version | Criteria | Cases |
|---|---|---|---|---|
{{POLICY_TABLE}}

### `criteria` ({{N_CRITERIA}} rows)

| Field | Type | Description |
|---|---|---|
| `ncd` | string | NCD display id |
| `criterion_id` | string | Criterion id within the NCD (`C1`, `C2`, ...) |
| `text` | string | Short paraphrase of the criterion |
| `span` | string | Verbatim span from the NCD text that states the criterion |
| `type` | string | Criterion category (see below) |

| `type` | Criteria |
|---|---|
{{CRITERIA_TYPE_TABLE}}

## How the cases were built

Please read this section before relying on the labels.

1. **Policy text.** All current NCDs were downloaded from the public CMS Coverage API on
   {{SNAPSHOT_DATE}}; HTML fields were converted to plain text. Nothing else in the policy text
   was edited.
2. **Criteria checklists.** For each NCD, the coverage criteria were written out as an explicit
   checklist (`criteria`). Each criterion has a `span` that was checked automatically to appear
   **verbatim** in the NCD text (after whitespace, hyphen and curly-quote normalization), so every
   gold citation points at real policy language.
3. **Vignettes.** The vignettes are **synthetic**. They were drafted **with LLM assistance** from
   the per-policy checklist by controlled perturbation: all criteria met (`covered`), one criterion
   contradicted by the facts (`not_covered`, with that criterion as the gold citation), or one
   criterion's evidence absent (`insufficient_documentation`), plus near-miss and distractor
   details. The gold label is meant to follow from the checklist by construction. No real patient
   data or PHI was used.
4. **Automatic consistency checks.** Every gold criterion id exists in the NCD's checklist,
   `covered` cases cite no criteria, `not_covered` cases cite at least one violated criterion, and
   `insufficient_documentation` cases cite only missing-documentation criteria.
5. **Expert review: pending.** **All {{N_UNREVIEWED}} of {{N_CASES}} labels are currently
   `draft_unreviewed`.** No clinician or certified coder has yet verified the checklists, the
   vignettes or the gold labels. Review is planned, and `review_status` will be updated per case
   when it is done. Until then, expect some labels to be wrong or debatable, especially where an
   NCD defers to local contractor discretion or where a vignette is ambiguous.

## Metrics

Computed by `scripts/score.py`:

| Metric | Definition |
|---|---|
| `accuracy` | 3-way decision accuracy |
| `macro_f1` | Macro-averaged F1 over the three decisions |
| `unsafe_approval_rate` | Share of gold `not_covered` / `insufficient_documentation` cases predicted `covered`. **Headline safety metric.** |
| `over_denial_rate` | Share of gold `covered` cases not predicted `covered` |
| `citation_recall` | Share of gold violated / missing criteria matched by at least one model quote (from `policy_quotes` or `missing_documentation`); a quote matches when it contains at least 50% of the criterion span's tokens |
| `parse_failure_rate` | Share of replies with no valid JSON decision (counted as wrong) |

## How to evaluate

The reference harness (Python standard library only) works with any OpenAI-compatible chat
endpoint (vLLM, Ollama, LM Studio, OpenRouter, hosted APIs):

```bash
# 1. Run a model (resumable; one JSON line per case)
python3 scripts/run_eval.py --base-url http://localhost:8000/v1 --model <model> \
    --out results/<model>.jsonl
# 2. Score one or more prediction files
python3 scripts/score.py results/*.jsonl
```

`scripts/run_eval.py` builds the prompt exactly as described under *Task definition* (temperature 0)
and extracts the last JSON object from the reply. If you use your own harness, keep the same
system prompt and policy formatting so results are comparable.

## Limitations

- **NCDs only.** Only National Coverage Determinations are included. Local Coverage
  Determinations (LCDs) and billing articles are excluded because they contain AMA CPT content
  that cannot be redistributed. Many real coverage decisions depend on LCDs, contractor
  discretion, the claim or other CMS manuals, none of which the model sees here.
- **Synthetic, unreviewed cases.** Vignettes are short and synthetic, written with LLM assistance,
  and not yet expert-reviewed (see above). Real medical records are longer, noisier and less
  explicit about which criteria are met.
- **Small scale.** {{N_CASES}} cases over {{N_POLICIES}} NCDs is a pilot. Per-policy results have
  high variance.
- **Snapshot in time.** CMS updates its coverage database frequently, often weekly. The policy
  text here reflects the snapshot of {{SNAPSHOT_DATE}}. Check the `version`, `effective_date` and
  `source_url` fields; a later NCD version may change the correct answer.
- **Contamination.** NCD text is public and probably present in pretraining data. The cases are
  new, but once published they may be too.
- **Not medical or billing advice.** This dataset is for research on model evaluation. It must not
  be used to make or support real coverage, billing, coding or clinical decisions.

## License

- **Data** (cases, criteria checklists, labels, annotations, this card): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- **NCD text** (`policies.jsonl`, and the `span` field in `criteria.jsonl`): a work of the US
  Government (CMS), not subject to copyright in the United States. The source is the CMS Medicare
  Coverage Database.
- **Code** (`scripts/`, the evaluation harness): Apache License 2.0.

See `LICENSE` in this repository.

## Citation

```bibtex
@misc{dobbali2026medcoverbench,
  title        = {MedCoverBench: Evaluating LLM Reasoning over Medicare National Coverage Determinations},
  author       = {Dobbali, Manoj},
  year         = {2026},
  howpublished = {Hugging Face dataset},
  url          = {https://huggingface.co/datasets/<hf-user>/MedCoverBench},
  note         = {Placeholder; update with the arXiv reference when available}
}
```
