# MedCoverBench

**Can a language model decide Medicare coverage from the real policy text?**

MedCoverBench tests whether LLMs can read a full CMS National Coverage Determination (NCD), apply
it to a patient case, cite the policy language that decides it, and recognize when required
documentation is missing.

> **Status: pre-release.** 50 NCDs, 513 cases, 434 criteria, 8 baseline models. Every label is `draft_unreviewed`
> until a clinician or certified coder signs off. Expect labels to change.

Project overview deck: <https://manojdobbali.com/projects/medcoverbench>

## The task

Each item gives the model the full NCD text and a synthetic patient case. The model returns JSON:

```json
{"decision": "covered | not_covered | insufficient_documentation",
 "policy_quotes": ["verbatim policy text for each deciding criterion"],
 "missing_documentation": ["each required item absent from the case"],
 "rationale": "2-4 sentences"}
```

| Decision | Meaning |
|---|---|
| `covered` | Every applicable criterion is met and documented. |
| `not_covered` | The facts show at least one applicable criterion is not met. |
| `insufficient_documentation` | Nothing is shown to be violated, but documentation the policy requires is missing. |

The headline metric is the **unsafe approval rate**: how often a model says `covered` when the gold
answer is `not_covered` or `insufficient_documentation`. `score.py` also reports accuracy,
macro-F1, over-denial rate, citation recall and parse failure rate.

## Baselines

All 513 cases, temperature 0, via OpenRouter (2026-10-28, after the case revision in
`IMPLEMENTATION_LOG.md` section 9d). Labels are still under review, so
these numbers will change.

| Model | Accuracy | Unsafe approval | Over-denial | Citation recall |
|---|---|---|---|---|
| GPT-5 mini | 0.967 | 0.009 | 0.023 | 0.992 |
| Qwen 3.7 Plus | 0.943 | 0.009 | 0.057 | 0.963 |
| Gemini 3.1 Flash Lite | 0.934 | 0.015 | 0.115 | 0.927 |
| DeepSeek V3.1 | 0.910 | 0.027 | 0.172 | 0.932 |
| Llama 3.3 70B | 0.893 | 0.086 | 0.109 | 0.870 |
| Qwen 2.5 72B | 0.848 | 0.180 | 0.075 | 0.930 |
| Qwen 2.5 7B | 0.622 | 0.224 | 0.276 | 0.718 |
| Llama 3.1 8B | 0.591 | 0.463 | 0.092 | 0.670 |

Predictions with raw replies are in `results/`. See `IMPLEMENTATION_LOG.md` section 9 for
per-class recall and the cases every strong model misses.

### Long-context track (pilot)

The case's NCD is hidden among 45 to 140 other real NCDs (about 32k and 96k tokens), and the
model must find it before deciding. Early result: Llama 3.3 70B still finds the right policy
93-98% of the time, but its unsafe approval rate rises from 8.7% with the policy alone to 28.8%
at 32k and 50% at 96k. See `IMPLEMENTATION_LOG.md` section 9c.

## Quick start

No dependencies beyond Python 3.9+.

```bash
# Evaluate any OpenAI-compatible endpoint (OpenRouter, vLLM, Ollama, LM Studio...)
export OPENROUTER_API_KEY=...
python3 scripts/run_eval.py --base-url https://openrouter.ai/api/v1 \
    --model qwen/qwen-2.5-7b-instruct --api-key-env OPENROUTER_API_KEY \
    --out results/qwen-2.5-7b-instruct.jsonl
python3 scripts/score.py results/*.jsonl

# Local model through Ollama
python3 scripts/run_eval.py --base-url http://localhost:11434/v1 --model qwen2.5:7b \
    --out results/qwen2.5-7b-local.jsonl
```

`run_eval.py` is resumable: it skips case ids already in the output file.

## Repository layout

| Path | Contents |
|---|---|
| `data/raw/ncd/` | All current NCDs from the CMS Coverage API, as cleaned text plus the original HTML |
| `data/specs/` | Per-policy source files: criteria with verbatim spans, and cases |
| `data/pilot/<ncd>/` | Generated `checklist.json` and `cases.jsonl` for each policy (all 50 live here) |
| `scripts/fetch_ncd.py` | Downloads every current NCD |
| `scripts/add_policy.py` | Validates a spec and writes its checklist and cases |
| `scripts/run_eval.py` | Runs a model over the cases |
| `scripts/score.py` | Scores result files |
| `scripts/export_hf.py` | Builds the Hugging Face release in `release/hf/` |
| `scripts/export_review_data.py` | Builds the data file for the expert label-review tool |
| `scripts/build_long_context.py` | Builds the long-context items in `data/long_context/` |
| `scripts/long_context_report.py` | Breaks long-context results down by depth and retrieval |
| `paper/` | Paper draft (LaTeX) |
| `results/` | Model predictions, with raw replies |
| `DESIGN.md` | Benchmark design |
| `IMPLEMENTATION_LOG.md` | Build history: every step, decision and fix |

## How cases are built

For each NCD, a checklist of atomic criteria is extracted. Each criterion is anchored to a span
copied verbatim from the policy. Cases are then written by controlled perturbation:
- all criteria met gives `covered`;
- one contradicted gives `not_covered`;
- one absent gives `insufficient_documentation`.

`add_policy.py` rejects a spec unless every span is found in the NCD text and every label is
consistent with the criteria it cites. Cases use only the NCD text, synthetic patients, and no CPT
codes. They were drafted with AI assistance and are under expert review. See
`IMPLEMENTATION_LOG.md` for the full process.

## Scope and licensing

- **NCDs only.** NCD text is a US government work. Local Coverage Determinations (LCDs) and
  billing articles contain AMA CPT content and are not included.
- **Data:** CC BY 4.0. **Code:** Apache 2.0 (`LICENSE`).
- **Not medical or billing advice.** The benchmark measures reasoning over policy text. It does
  not determine anyone's coverage.
- **Snapshot:** CMS updates NCDs weekly. This snapshot was taken 2026-10-27.

## Contributing

The most valuable contribution right now is **label review** by clinicians and certified coders.
Open an issue or reach out through <https://manojdobbali.com>.

## Citation

```bibtex
@misc{dobbali2026medcoverbench,
  title  = {MedCoverBench: Evaluating LLM Reasoning over Medicare National Coverage Determinations},
  author = {Dobbali, Manoj},
  year   = {2026},
  url    = {https://github.com/mdobbali/medcoverbench}
}
```
