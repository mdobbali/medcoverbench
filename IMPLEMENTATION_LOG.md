# MedCoverBench implementation log

This log records what was built, in what order, and why, so that a new contributor can rebuild
the dataset from scratch and understand each decision. Read `DESIGN.md` for the benchmark design
itself; this file is the build history.

Status as of 2026-10-27: 50 policies, 513 cases, 434 criteria. Every label is
`draft_unreviewed`. Nothing has been published.

---

## 1. What MedCoverBench is

A benchmark for one question: given the full text of a Medicare National Coverage Determination
(NCD) and a patient case, can a language model decide whether Medicare covers the requested
service, cite the policy language that decides it, and notice when required documentation is
missing?

Each case has one of three gold decisions:

| Decision | Meaning |
|---|---|
| `covered` | Every applicable criterion is met and documented. |
| `not_covered` | The facts show at least one applicable criterion is not met. |
| `insufficient_documentation` | Nothing is shown to be violated, but documentation the policy requires is missing. |

The headline safety metric is the **unsafe approval rate**: how often a model says `covered`
when the gold answer is anything else.

## 2. Timeline

| Date | Step |
|---|---|
| 2026-10-24 | Prior-art search. Medicare coverage reasoning over real CMS policy had no public benchmark; this became the project. |
| 2026-10-24 | Confirmed the name MedCoverBench was unused on Hugging Face, GitHub and arXiv. Wrote `DESIGN.md`. |
| 2026-10-24 | Downloaded all 345 current NCDs from the CMS Coverage API (`scripts/fetch_ncd.py`). |
| 2026-10-24 | Ranked NCDs by how checkable their criteria are (`scripts/shortlist_ncd.py`). |
| 2026-10-24 | Wrote the first two policies by hand: 210.14 lung cancer screening and 240.4 CPAP. |
| 2026-10-24 | Built the evaluation harness (`run_eval.py`) and scorer (`score.py`) and checked both against a stub server whose expected scores were known. |
| 2026-10-24 | Added `add_policy.py` so every later policy is written as a spec file and validated. Added 8 more policies, for a 10-policy, 98-case pilot. |
| 2026-10-24 | First real model run: Qwen 2.5 7B Instruct via OpenRouter, 98 cases. |
| 2026-10-27 | Expanded to 50 policies in parallel (section 6). Rewrote the deep brain stimulation cases, which were too easy. |
| 2026-10-27 | Built the Hugging Face export and dataset card (`scripts/export_hf.py`, `release/hf/`). |
| 2026-10-27 | Found and fixed a text-cleaning bug in `fetch_ncd.py` (section 7). Re-downloaded all NCDs, re-validated every case, re-ran Qwen 2.5 7B on 506 of 513 cases. |

## 3. Data source and licensing

- **Source:** CMS Coverage API, `https://api.coverage.cms.gov/v1`.
  - `/reports/national-coverage-ncd/` lists the current NCDs (345 on 2026-10-27).
  - `/data/ncd/?ncdid=&ncdver=` returns one NCD's full text. No key or license token is needed.
- **NCDs only.** Local Coverage Determinations (LCDs) and billing articles need an AMA CPT
  license token to download and cannot be redistributed, so they are excluded. Some well-known
  rules live only in LCDs (for example, the CPAP 4-hours-on-70%-of-nights adherence rule). Cases
  never test an LCD rule, and some use one as a distractor that the model should ignore.
- **No CPT codes** appear in any case. ICD-10-CM and HCPCS Level II are public and allowed.
- **Licenses:** NCD text is a US government work. Data is CC BY 4.0, code is Apache 2.0.
- **Freshness:** CMS updates the API weekly, so every release records a snapshot date.

## 4. Pipeline

```
fetch_ncd.py      CMS API  ->  data/raw/ncd/<ncd>_v<ver>.json   (text + original HTML)
shortlist_ncd.py  rank NCDs by checkable criteria
data/specs/<ncd>.json        hand-authored: criteria (verbatim spans) + cases
add_policy.py     spec  ->  data/pilot/<ncd>/checklist.json + cases.jsonl   (validated)
run_eval.py       cases + policy text  ->  results/<model>.jsonl            (any OpenAI-compatible API)
score.py          results  ->  accuracy, macro-F1, unsafe approval, over-denial, citation recall
export_hf.py      data/pilot + data/raw  ->  release/hf/  (cases, policies, criteria, dataset card)
```

All scripts use the Python 3.9 standard library only. No packages to install.

## 5. How a policy is built

1. **Read the full NCD**, i.e. the three fields the model will see: `item_service_description`,
   `indications_limitations` and `reasons_for_denial`.
2. **Extract a criteria checklist.** Each criterion is one checkable requirement with an id
   (`C1`, `C2`...), a short paraphrase, a type (eligibility, exclusion, provider, documentation,
   frequency, device, setting, exception, continuation) and a **span copied verbatim from the NCD**.
3. **Write about 10 cases** by controlled perturbation, so that the gold label follows from the checklist:
   - all criteria met gives `covered`;
   - one criterion contradicted gives `not_covered`, and that criterion is the gold citation;
   - one criterion's evidence simply absent gives `insufficient_documentation`.

   Cases are written to discriminate:
   - exact boundary values that still qualify;
   - violations buried among many satisfied details;
   - exceptions the policy grants;
   - distractors that sound disqualifying but aren't under this NCD.
4. **Write a rationale note** for each case, explaining its label.
5. **Run `add_policy.py`**, which refuses the spec unless all of these hold:
   - every span appears verbatim in the NCD text (normalized only for quotes, whitespace and hyphens);
   - every referenced criterion id exists;
   - a `covered` case cites no criteria, a `not_covered` case cites a violated criterion, and an
     `insufficient_documentation` case cites only missing ones.
6. **Record ambiguities** in the spec's `notes` field. If the policy text is unclear, no case is
   allowed to depend on the unclear part.

Rules for every case author:
- Use only the NCD text: no LCD rules and no clinical knowledge the policy doesn't state.
- Drop any case whose label is uncertain.
- Use synthetic patients only, with no real people and no PHI.
- Skip NCDs that are mostly contractor discretion, a blanket non-coverage or a "covered only in
  an approved study" rule. These can't yield about 8 good cases.

The cases were drafted with AI assistance (Claude, working in Claude Code) under these rules. They
must be reviewed by a clinician or certified coder before being called gold, and the paper and
dataset card say so.

## 6. Scaling from 10 to 50 policies

The pilot covered 10 policies. On 2026-10-27, the expansion to about 500 cases was split into
independent jobs that ran in parallel, each writing only its own files:

| Job | Policies | Result |
|---|---|---|
| Cardiovascular | 20.36, 20.38, 20.37, 20.39, 20.9.1, 20.7, 20.29, 20.35, 260.9, 20.6 | 103 cases. 20.8.4 leadless pacemakers was swapped for 20.6 because its only criterion is study enrollment. |
| Neuro, musculoskeletal, DME | 160.18, 150.2, 160.12, 280.14, 280.8, 280.7, 280.3, 240.2, 280.6, 160.7 | 106 cases. 160.27 TENS (now a blanket non-coverage) and 150.13 PILD (study-only) were swapped for spares. |
| Screening, labs, imaging | 210.3, 220.6.13, 90.1, 190.14, 210.7, 210.12, 210.2, 220.6.1, 90.2, 210.13 | 98 cases. Ambiguous cases dropped from 190.14 and 210.2. |
| Transplant and other | 110.23, 110.4, 240.1, 260.3, 260.1, 50.3, 100.1, 110.14, 70.2.1, 230.10 | 105 cases. |
| Harder DBS cases | 160.24 | Rewritten from 10 to 13 cases. Qwen 7B had scored 10/10 because each old case stated its violation in policy wording in the first sentence. |
| Release packaging | (none) | `export_hf.py`, dataset card template, LICENSE files. |

Each job read the same instructions: `DESIGN.md`, `add_policy.py`, two example specs, the model's
system prompt, and the rules in section 5. Every spec it produced passed `add_policy.py`.

The expansion also fixed a class imbalance: the pilot had only 9 `insufficient_documentation`
cases, and the 50-policy set has 90.

## 7. Bug found and fixed: text lost around "<" and ">"

**Symptom.** Case authors reported policy text that stopped mid-sentence, e.g. the ventricular
assist device NCD read "have a Cardiac Index (CI)" with nothing after it.

**Cause.** The CMS API returns HTML that is itself HTML-escaped. `fetch_ncd.py` unescaped twice
and only then stripped tags, so a literal `&amp;lt; 2.2` became `<`, and the tag-stripping
regular expression deleted everything from it to the next `>`.

**Fix.** Unescape once, strip tags, then unescape the remaining text. The script also now keeps
the original HTML in each file under `source_html`, so cleaning can be redone without
re-downloading.

**Impact.**
- 12 of the 345 NCDs had lost text. 4 of them are in the benchmark:
  - 20.39 (+354 characters: study subgroup list);
  - 20.9.1 (+75: "< 2.2 L/min/m2, while not on inotropes...");
  - 240.1 (+118: "LVEF <45%; ... arrhythmia (>5 ...");
  - 240.9 (+42: "Normalization (< 46 mmHg) of PaCO2").
- Every criterion span still matched the corrected text.
- The cases in the 4 affected policies were checked by hand; no gold label depended on the lost text.
- The Qwen pilot run, which had used the flawed text for 240.9, was set aside
  (`results/qwen-2.5-7b-instruct.pilot98-buggytext.jsonl`), and the model was re-run.
- The flawed download is kept outside the repository for reference only.

Two other reported oddities are genuine features of the CMS text, not this bug:
- 210.3 has no colonoscopy section in the current version;
- 210.2 contains the garbled phrase "Fewer than three negative or any pap smears".

Both are noted in their specs for reviewers.

**Lesson.** Validate the cleaning against the source. A spot check of policies containing
inequalities would have caught this on day one.

## 8. Evaluation harness

- `run_eval.py` sends the system prompt, the policy text and the case to any OpenAI-compatible
  `/chat/completions` endpoint (OpenRouter, vLLM, Ollama, LM Studio).
  - It runs at temperature 0 and retries on 429 and 5xx errors.
  - It is resumable: ids already in the output file are skipped.
  - The API key is read from an environment variable named by `--api-key-env`, never from a file.
- The parser strips `<think>` blocks and takes the last JSON object whose `decision` is valid. A
  reply without one counts as a parse failure and is scored wrong.
- `score.py` metrics:
  - accuracy and macro-F1 (3 classes);
  - unsafe approval rate;
  - over-denial rate (gold `covered`, predicted otherwise);
  - citation recall: a gold criterion counts as cited when a quote shares at least 50% of the
    criterion span's tokens;
  - parse failure rate.
- The harness was verified on a stub server with known answers before any real model was run.
- A native Anthropic SDK backend for Claude models is planned. It needs an Anthropic API key.

## 9. Results so far

Qwen 2.5 7B Instruct (OpenRouter, temperature 0) is used only as a smoke test that the pipeline
works end to end. These are not the paper's baselines.

| Run | Cases | Accuracy | Macro-F1 | Unsafe approval | Over-denial | Citation recall | Parse failures |
|---|---|---|---|---|---|---|---|
| Pilot, 2026-10-24 (pre-fix text) | 98 | 0.673 | 0.531 | 0.238 | 0.257 | 0.635 | 0.000 |
| Full set, 2026-10-27 (corrected text) | 506 of 513 | 0.628 | 0.548 | 0.220 | 0.276 | 0.707 | 0.006 |

The 7 unscored cases (260.3-05 to 260.3-11) were stopped by a provider billing error (HTTP 402).
They are filled in by the baseline run in section 9a, since `run_eval.py` skips cases already scored. The run used 6 parallel streams, one output file per policy in
`results/shards/`, merged into `results/qwen-2.5-7b-instruct.jsonl`. The pilot file can no longer be
compared case for case, because the 160.24 cases were rewritten after it was produced.

Confusion on the full set (rows gold, columns predicted):

| Gold | covered | not_covered | insufficient_documentation | unparseable |
|---|---|---|---|---|
| covered (174) | 126 | 46 | 1 | 1 |
| not_covered (244) | 68 | 176 | 0 | 0 |
| insufficient_documentation (88) | 5 | 65 | 16 | 2 |

Patterns in the pilot misses:
- The model never chose `insufficient_documentation`.
- It missed waiting periods, e.g. approving an ICD 21 days after an MI against the 40-day rule.
- It denied cases at exact boundaries, e.g. CHA₂DS₂-VASc exactly 3.
- It demanded shared decision-making where the policy exempts it.

## 10. Hugging Face release (prepared, not published)

`python3 scripts/export_hf.py` writes `release/hf/`:
- `data/cases.jsonl`, `data/policies.jsonl` and `data/criteria.jsonl`, sorted and deterministic;
- `README.md`, the dataset card, rendered from `README.template.md` with live counts and the snapshot date;
- `LICENSE` (CC BY 4.0, plus a note on the NCD public-domain status).

Each policy row links to its CMS page:
`https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=<id>&ncdver=<ver>`.

Before publishing:
1. Expert review of the labels.
2. Set the Hugging Face namespace in the card.
3. Add the arXiv citation.
4. Re-run the export.

## 11. Open items

- **Expert review (blocking).** A clinician or certified coder must review every label. Start
  with the cases flagged in each spec's `notes`. Notable ones:
  - 20.40, where "≥140 systolic **and** >90 diastolic" is read literally;
  - 50.3, the "may" cover IDE trial;
  - 70.2.1, missing exam elements treated as insufficient documentation;
  - 110.23, amyloidosis at EF exactly 45%;
  - 220.6.1, exercise-stress PET labelled not covered.
- **Baselines.** Run several open and frontier models. Paid models need OpenRouter credits.
- **Claude backend** for `run_eval.py` using the Anthropic SDK.
- **Held-out test split** and a leaderboard, to limit contamination.
- **Long-context track:** the target NCD buried among 10-50 other NCDs.

## 12. Reproducing from scratch

```bash
python3 scripts/fetch_ncd.py                        # ~10 min, 345 NCDs
for f in data/specs/*.json; do python3 scripts/add_policy.py "$f"; done
OPENROUTER_API_KEY=... python3 scripts/run_eval.py \
    --base-url https://openrouter.ai/api/v1 --model qwen/qwen-2.5-7b-instruct \
    --api-key-env OPENROUTER_API_KEY --out results/qwen-2.5-7b-instruct.jsonl
python3 scripts/score.py results/qwen-2.5-7b-instruct.jsonl
python3 scripts/export_hf.py
```

The two hand-written pilot policies (210.14 and 240.4) live in `data/pilot/` without a spec file.
A newer CMS version of a policy can invalidate a span; `add_policy.py` will report which one.

## Appendix: policies

| NCD | Title | Criteria | Covered | Not covered | Insufficient doc |
|---|---|---|---|---|---|
| 20.4 | Implantable Cardioverter Defibrillators (ICDs) | 13 | 4 | 5 | 1 |
| 20.6 | Transmyocardial Revascularization (TMR) | 9 | 3 | 5 | 2 |
| 20.7 | Percutaneous Transluminal Angioplasty (PTA) | 9 | 4 | 5 | 2 |
| 20.9.1 | Ventricular Assist Devices | 9 | 4 | 5 | 2 |
| 20.29 | Hyperbaric Oxygen Therapy | 9 | 4 | 5 | 2 |
| 20.32 | Transcatheter Aortic Valve Replacement (TAVR) | 10 | 3 | 6 | 1 |
| 20.33 | Transcatheter Edge-to-Edge Repair (TEER) for Mitral Valve Regurgitation | 11 | 4 | 5 | 1 |
| 20.34 | Percutaneous Left Atrial Appendage Closure (LAAC) | 9 | 3 | 6 | 1 |
| 20.35 | Supervised Exercise Therapy (SET) for Symptomatic Peripheral Artery Disease | 8 | 3 | 5 | 2 |
| 20.36 | Implantable Pulmonary Artery Pressure Sensors for Heart Failure | 10 | 3 | 5 | 2 |
| 20.37 | Transcatheter Tricuspid Valve Replacement (TTVR) | 6 | 3 | 5 | 2 |
| 20.38 | Transcatheter Edge-to-Edge Repair for Tricuspid Valve Regurgitation | 6 | 3 | 5 | 2 |
| 20.39 | Cardiac Contractility Modulation (CCM) for Heart Failure | 6 | 3 | 5 | 2 |
| 20.40 | Renal Denervation (RDN) for Uncontrolled Hypertension | 9 | 2 | 7 | 1 |
| 50.3 | Cochlear Implantation | 5 | 3 | 5 | 2 |
| 70.2.1 | Diagnosis and Treatment of Diabetic Sensory Neuropathy with LOPS | 6 | 3 | 4 | 2 |
| 90.1 | Pharmacogenomic Testing for Warfarin Response | 7 | 3 | 5 | 2 |
| 90.2 | Next Generation Sequencing (NGS) | 11 | 3 | 5 | 2 |
| 100.1 | Bariatric Surgery for Co-Morbid Conditions Related to Morbid Obesity | 9 | 3 | 5 | 2 |
| 110.4 | Extracorporeal Photopheresis | 4 | 3 | 5 | 2 |
| 110.14 | Apheresis (Therapeutic Pheresis) | 9 | 4 | 5 | 2 |
| 110.23 | Stem Cell Transplantation | 14 | 4 | 7 | 2 |
| 150.2 | Osteogenic Stimulators | 9 | 4 | 6 | 2 |
| 160.7 | Electrical Nerve Stimulators | 6 | 3 | 5 | 2 |
| 160.12 | Neuromuscular Electrical Stimulation (NMES) | 9 | 3 | 6 | 2 |
| 160.18 | Vagus Nerve Stimulation (VNS) | 9 | 4 | 5 | 2 |
| 160.24 | Deep Brain Stimulation for Essential Tremor and Parkinson's Disease | 15 | 4 | 6 | 3 |
| 190.14 | HIV Testing (Diagnosis) | 9 | 4 | 4 | 1 |
| 200.3 | Monoclonal Antibodies Directed Against Amyloid for Alzheimer's Disease | 6 | 4 | 5 | 1 |
| 210.2 | Screening Pap Smears and Pelvic Examinations | 8 | 4 | 3 | 2 |
| 210.3 | Colorectal Cancer Screening Tests | 13 | 3 | 5 | 2 |
| 210.7 | Screening for HIV Infection | 7 | 4 | 4 | 2 |
| 210.12 | Intensive Behavioral Therapy for Obesity | 8 | 3 | 5 | 2 |
| 210.13 | Screening for Hepatitis C Virus (HCV) in Adults | 6 | 3 | 5 | 2 |
| 210.14 | Lung Cancer Screening with Low Dose CT (LDCT) | 8 | 3 | 4 | 1 |
| 220.6.1 | PET for Perfusion of the Heart | 7 | 4 | 4 | 2 |
| 220.6.13 | FDG PET for Dementia and Neurodegenerative Diseases | 11 | 3 | 5 | 2 |
| 230.10 | Incontinence Control Devices | 8 | 3 | 5 | 2 |
| 240.1 | Lung Volume Reduction Surgery | 12 | 3 | 5 | 2 |
| 240.2 | Home Use of Oxygen | 9 | 4 | 4 | 2 |
| 240.4 | CPAP Therapy for Obstructive Sleep Apnea | 9 | 4 | 5 | 1 |
| 240.9 | NIPPV in the Home for Chronic Respiratory Failure | 7 | 5 | 5 | 0 |
| 260.1 | Adult Liver Transplantation | 8 | 4 | 5 | 2 |
| 260.3 | Pancreas Transplants | 7 | 4 | 5 | 2 |
| 260.9 | Heart Transplants | 5 | 4 | 4 | 2 |
| 280.3 | Mobility Assistive Equipment (MAE) | 10 | 4 | 5 | 2 |
| 280.6 | Pneumatic Compression Devices | 8 | 3 | 5 | 2 |
| 280.7 | Hospital Beds | 8 | 4 | 4 | 2 |
| 280.8 | Air-Fluidized Bed | 11 | 3 | 5 | 2 |
| 280.14 | Infusion Pumps | 12 | 4 | 5 | 2 |
| **Total** | **50 policies** | **434** | **174** | **249** | **90** |
