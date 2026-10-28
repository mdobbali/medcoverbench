# MedCoverBench implementation log

This log records what was built, in what order, and why, so that a new contributor can rebuild
the dataset from scratch and understand each decision. Read `DESIGN.md` for the benchmark design
itself; this file is the build history.

Status as of 2026-10-27: 50 policies, 513 cases, 434 criteria, 8 baseline models. Every label is
`draft_unreviewed`. The dataset is not yet published.

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
| 2026-10-27 | Ran 8 baseline models on all 513 cases ($4.26). Built the expert review tool. Prepared the GitHub repository. |
| 2026-10-27 | Found and fixed a text-cleaning bug in `fetch_ncd.py` (section 7). Re-downloaded all NCDs, re-validated every case, re-ran Qwen 2.5 7B on all 513 cases. |

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

## 9. Results

### 9a. Baselines (2026-10-27)

Eight models were run on all 513 cases through OpenRouter at temperature 0, with
`--max-tokens 8000` so that reasoning models aren't cut off. Each model ran as 4 parallel streams
(one output file per policy, merged into `results/<model>.jsonl`), with a retry pass for
transient provider errors. A spend guard polled the account usage and would have stopped every
run at $5. The total cost was $4.26.

| Model | Accuracy | Macro-F1 | Unsafe approval | Over-denial | Citation recall | Parse failures |
|---|---|---|---|---|---|---|
| openai/gpt-5-mini | 0.943 | 0.937 | 0.009 | 0.098 | 0.992 | 0.008 |
| google/gemini-3.1-flash-lite | 0.932 | 0.930 | 0.009 | 0.126 | 0.921 | 0.002 |
| qwen/qwen3.7-plus | 0.922 | 0.899 | 0.009 | 0.121 | 0.963 | 0.000 |
| deepseek/deepseek-chat-v3.1 | 0.904 | 0.914 | 0.027 | 0.201 | 0.930 | 0.008 |
| meta-llama/llama-3.3-70b-instruct | 0.885 | 0.897 | 0.088 | 0.121 | 0.876 | 0.012 |
| qwen/qwen-2.5-72b-instruct | 0.846 | 0.869 | 0.174 | 0.092 | 0.927 | 0.000 |
| qwen/qwen-2.5-7b-instruct | 0.630 | 0.547 | 0.215 | 0.276 | 0.710 | 0.006 |
| meta-llama/llama-3.1-8b-instruct | 0.593 | 0.575 | 0.463 | 0.092 | 0.656 | 0.016 |

Recall per gold class (covered / not covered / insufficient documentation):

| Model | Covered | Not covered | Insufficient doc |
|---|---|---|---|
| gpt-5-mini | 0.90 | 0.98 | 0.91 |
| gemini-3.1-flash-lite | 0.87 | 0.98 | 0.92 |
| qwen3.7-plus | 0.88 | 0.98 | 0.84 |
| deepseek-chat-v3.1 | 0.80 | 0.96 | 0.94 |
| llama-3.3-70b-instruct | 0.88 | 0.88 | 0.90 |
| qwen-2.5-72b-instruct | 0.91 | 0.77 | 0.93 |
| qwen-2.5-7b-instruct | 0.72 | 0.73 | 0.18 |
| llama-3.1-8b-instruct | 0.91 | 0.45 | 0.37 |

What this says:
- **Single-policy cases are nearly saturated for strong models.** The top four reach 90-94%
  accuracy with unsafe approval at or under 2.7%. 197 of 513 cases are solved by all eight
  models. The benchmark needs harder cases and the long-context track to separate frontier
  models.
- **Unsafe approval separates models that accuracy ranks closely.** Qwen 2.5 72B reaches 85%
  accuracy but approves 17% of denials. Llama 3.1 8B approves 46%.
- **Errors lean toward denial in strong models.** Their misses are mostly over-denials (10-20%),
  not unsafe approvals.
- **Small models can't use the third label.** Qwen 2.5 7B recovers only 18% of
  insufficient-documentation cases, calling most of them not covered.

**Candidate label errors.** These 7 cases are missed by all four strongest models. They go to
expert reviewers first:

| Case | Gold | Strong models said | Note |
|---|---|---|---|
| 20.40-05 | insufficient_documentation | not_covered (4/4) | No documented screening for obstructive sleep apnea |
| 210.2-01 | covered | split not_covered / insufficient | Pap smear NCD text is garbled |
| 210.2-03 | covered | split | Pap smear NCD; high-risk factor count |
| 210.2-06 | covered | split | Pap smear NCD; childbearing age |
| 210.3-10 | covered | split | Boundary: age exactly 85, sensitivity and specificity exactly at threshold |
| 280.14-02 | covered | not_covered (3/4) | C-peptide at 180% of LLN with the renal-insufficiency 200% cutoff |
| 280.7-10 | covered | split | Hospital bed; inability to operate controls |

Three of the seven come from 210.2, whose CMS text is internally garbled (section 7). These cases
may be hard, or the label may be wrong. A reviewer decides.

### 9b. Qwen 2.5 7B smoke tests

| Run | Cases | Accuracy | Macro-F1 | Unsafe approval | Over-denial | Citation recall | Parse failures |
|---|---|---|---|---|---|---|---|
| Pilot, 2026-10-24 (pre-fix text) | 98 | 0.673 | 0.531 | 0.238 | 0.257 | 0.635 | 0.000 |
| Full set, 2026-10-27 (corrected text) | 513 | 0.630 | 0.547 | 0.215 | 0.276 | 0.710 | 0.006 |

The pilot file can't be compared case for case with the full run, because the 160.24 cases were
rewritten after it was produced.

Patterns in the Qwen 2.5 7B misses:
- It rarely chose `insufficient_documentation`: 16 of 90, calling 67 of them not covered.
- It missed waiting periods, e.g. approving an ICD 21 days after an MI against the 40-day rule.
- It denied cases at exact boundaries, e.g. CHA₂DS₂-VASc exactly 3 and AHI exactly 15.
- It demanded shared decision-making where the policy exempts it.

### 9c. Long-context pilot (2026-10-28)

**Build.** `scripts/build_long_context.py` writes `data/long_context/items-32k.jsonl` and
`items-96k.jsonl`:
- 120 cases, 40 per decision, spread across all 50 policies. The 7 candidate label errors above are
  excluded.
- Each case's NCD is hidden in a library of other real NCDs, about half from the same chapter.
- Excluded from each library: the target's parent and child NCDs, and any NCD that cross-references
  the target or that the target cross-references.
- The 32k library is a subset of the 96k one, so a change between sizes comes from length.
- The target's depth cycles through 0, 0.25, 0.5, 0.75 and 1.
- Libraries average 45 NCDs at 32k and 139 at 96k. Actual prompts are about 27-28k and 80k tokens.

The model isn't told which NCD applies and must also return `"ncd"`. `run_eval.py --items` runs the
track, `score.py` adds `ncd_accuracy`, and `scripts/long_context_report.py` breaks results down by
depth and by right or wrong NCD.

**Pilot runs.** Credits allowed only the cheaper models at first; the pilot cost $3.81. Numbers
below are after the case revision in 9d (the affected 55 items were re-run).

| Model | Accuracy (1 NCD / 32k / 96k) | Unsafe approval (1 NCD / 32k / 96k) | NCD accuracy (32k / 96k) |
|---|---|---|---|
| Gemini 3.1 Flash Lite | 0.933 / 0.900 / - | 0.037 / 0.050 / - | 1.000 / - |
| Llama 3.3 70B | 0.883 / 0.750 / 0.633 | 0.087 / 0.288 / 0.500 | 0.983 / 0.933 |
| Llama 3.1 8B | 0.600 / 0.558 / 0.175 | 0.388 / 0.412 / 0.175* | 0.875 / 0.225 |

"1 NCD" is the single-policy result on the same 120 cases. *66% of Llama 8B's replies at 96k are
invalid JSON. 95% bootstrap intervals for Llama 70B's unsafe approval: 18.8-38.8% at 32k and
38.8-60.0% at 96k, both above its 8.7% single-policy rate.

What this says:
- **Finding the policy isn't the bottleneck.** Gemini and Llama 70B name the right NCD 93-100% of
  the time, but still lose accuracy. Among cases where Llama 70B names the right NCD, accuracy is
  75% at 32k and 62% at 96k.
- **Long context makes models approve.** Llama 70B's unsafe approval goes 8.7% → 28.8% → 50%,
  while its over-denial goes 10% → 7.5% → 0%.
- **Position matters for Llama 70B** at 32k (23/24 correct at depth 0, 14/24 at 0.5). Gemini
  shows no position effect.
- **Llama 8B collapses at 96k:** mostly invalid JSON, and the right NCD only 22.5% of the time.

Chosen for the paper (2026-10-28): GPT-5 mini at both sizes and Gemini at 96k (about $8). Qwen 3.7
Plus and DeepSeek V3.1 are not run on this track. The runs stopped part-way when the API key hit
its own $10 limit (separate from the account balance); they resume from where they stopped.

### 9d. Case revision after the baselines (2026-10-28)

Strong models' over-denials exposed two construction gaps:
- Every case's "requested service" was the policy-level name. For 280.7 that name includes
  variable-height and electric features, while several vignettes order a manual bed. GPT-5 mini read
  the request as including the features and denied 280.7-01, -02 and -10.
- Cases didn't say whether program- and claim-level requirements are met: TAVR and TEER registry
  requirements, claim diagnosis coding for Pap smears, and the post-approval study for blood-based
  colorectal screening. 10 of GPT-5 mini's 17 over-denials asked for these.

Fix, with no label changed:
- `add_policy.py` accepts an optional per-case `service`.
- 280.7, 210.2 and 210.3 cases name the specific service requested.
- 20.32 and 20.33 vignettes state that the registry meets the NCD's registry requirements. The
  20.32 case where the hospital has no registry is unchanged.
- 210.2 cases state that the claim carries the risk-status diagnosis code.
- 210.3 biomarker cases state that the test meets its post-approval study requirement.

The 49 cases were re-run on all 8 models; the old outputs aren't kept in the repo.

| Model | Accuracy before → after | Over-denial before → after | Unsafe approval before → after |
|---|---|---|---|
| GPT-5 mini | 0.943 → 0.967 | 0.098 → 0.023 | 0.009 → 0.009 |
| Qwen 3.7 Plus | 0.922 → 0.943 | 0.121 → 0.057 | 0.009 → 0.009 |
| Gemini 3.1 Flash Lite | 0.932 → 0.934 | 0.126 → 0.115 | 0.009 → 0.015 |
| DeepSeek V3.1 | 0.904 → 0.910 | 0.201 → 0.172 | 0.027 → 0.027 |

Cases missed by all four strongest models fell from 7 to 2 (20.40-05 and 280.14-02). Five of the
seven were explained by construction rather than by a wrong label. The review tool's "Start here"
list and the long-context sample still use the original seven, so the long-context items are unchanged.

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
- **Frontier baselines.** Add Claude (native Anthropic SDK backend, needs an API key) and larger frontier models (GPT-5.x, Gemini Pro).
- **Harder cases.** Strong models are near the ceiling; add multi-criteria interactions, distractor NCDs and the long-context track.
- **Claude backend** for `run_eval.py` using the Anthropic SDK.
- **Held-out test split** and a leaderboard, to limit contamination.
- **Long-context track:** built and piloted (9c). GPT-5 mini (both sizes) and Gemini (96k) resume
  once the API key's own spending limit is raised.
- **Presumed facts in other policies.** 9d fixed the five policies where baselines exposed gaps;
  others may have program- or claim-level requirements that cases don't state.
- **Paper:** draft in `paper/main.tex` (LaTeX, not yet compiled). Remaining TBD cells await the
  long-context runs.

## 12. Reproducing from scratch

```bash
python3 scripts/fetch_ncd.py                        # ~10 min, 345 NCDs
for f in data/specs/*.json; do python3 scripts/add_policy.py "$f"; done
OPENROUTER_API_KEY=... python3 scripts/run_eval.py \
    --base-url https://openrouter.ai/api/v1 --model qwen/qwen-2.5-7b-instruct \
    --api-key-env OPENROUTER_API_KEY --out results/qwen-2.5-7b-instruct.jsonl
python3 scripts/score.py results/qwen-2.5-7b-instruct.jsonl
python3 scripts/export_hf.py
# Long-context track
python3 scripts/build_long_context.py
OPENROUTER_API_KEY=... python3 scripts/run_eval.py \
    --base-url https://openrouter.ai/api/v1 --model meta-llama/llama-3.3-70b-instruct \
    --api-key-env OPENROUTER_API_KEY --max-tokens 8000 \
    --items data/long_context/items-32k.jsonl --out results/long_context/llama-3.3-70b-instruct-lc32k.jsonl
python3 scripts/score.py results/long_context/*.jsonl
python3 scripts/long_context_report.py results/long_context/*.jsonl
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
