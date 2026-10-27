#!/usr/bin/env python3
"""Run a model on benchmark cases through any OpenAI-compatible chat endpoint.

Works with vLLM, Ollama, LM Studio, OpenRouter, OpenAI, and Anthropic's OpenAI-compatible API.
Writes one JSON line per case to the output file and skips cases already present (resumable).

Example:
  python3 scripts/run_eval.py --base-url http://localhost:11434/v1 --model qwen2.5:7b \\
      --out results/qwen2.5-7b.jsonl
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_FIELDS = [("Item/Service Description", "item_service_description"),
                 ("Indications and Limitations of Coverage", "indications_limitations"),
                 ("Reasons for Denial", "reasons_for_denial")]

SYSTEM = """You are a Medicare coverage reviewer. Decide whether the requested service is covered under the \
National Coverage Determination (NCD) provided, using only that policy and the case facts.

Decisions:
- "covered": every applicable coverage criterion is met and documented.
- "not_covered": the facts show at least one applicable criterion is not met.
- "insufficient_documentation": no criterion is shown to be violated, but documentation required by the policy is missing.

Respond with only a JSON object:
{"decision": "covered" | "not_covered" | "insufficient_documentation",
 "policy_quotes": ["verbatim text from the policy for each criterion that determines the decision"],
 "missing_documentation": ["each required item absent from the case"],
 "rationale": "2-4 sentences"}"""

DECISIONS = {"covered", "not_covered", "insufficient_documentation"}


def load_policy(ncd_id):
    paths = sorted(glob.glob(os.path.join(ROOT, "data", "raw", "ncd", "%s_v*.json" % ncd_id)))
    if not paths:
        sys.exit("NCD %s not downloaded; run scripts/fetch_ncd.py" % ncd_id)
    doc = json.load(open(paths[-1]))
    parts = ["NCD %s: %s" % (doc["document_display_id"], doc["title"])]
    parts += ["## %s\n%s" % (label, doc[key]) for label, key in POLICY_FIELDS if doc.get(key)]
    return "\n\n".join(parts)


def build_messages(case, policy):
    user = "# Policy\n\n%s\n\n# Case\n\nRequested service: %s\n\n%s" % (policy, case["service"], case["vignette"])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def chat(base_url, api_key, model, messages, max_tokens, retries=4):
    body = json.dumps({"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.load(resp)
            if not data.get("choices"):
                # Routers such as OpenRouter can return HTTP 200 with an upstream error body.
                if attempt < retries - 1:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise RuntimeError("no choices in response: %s" % str(data.get("error", data))[:300])
            return data["choices"][0]["message"]["content"] or "", data.get("usage", {})
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(5 * 2 ** attempt)
                continue
            raise


def parse(text):
    """Pull the last JSON object out of the reply; reasoning models often think out loud first."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            obj = json.loads(text[m.start():text.rfind("}") + 1])
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("decision") in DECISIONS:
            return obj
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", default="", help="name of the env var holding the API key")
    ap.add_argument("--cases", default=os.path.join(ROOT, "data", "pilot", "*", "cases.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=int, default=2048)
    args = ap.parse_args()

    api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    cases = [json.loads(l) for p in sorted(glob.glob(args.cases)) for l in open(p) if l.strip()]
    done = set()
    if os.path.exists(args.out):
        done = {json.loads(l)["id"] for l in open(args.out) if l.strip()}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    policies = {}
    with open(args.out, "a") as out:
        for case in cases:
            if case["id"] in done:
                continue
            policy = policies.setdefault(case["ncd"], load_policy(case["ncd"]))
            start = time.time()
            text, usage = chat(args.base_url, api_key, args.model, build_messages(case, policy), args.max_tokens)
            pred = parse(text)
            out.write(json.dumps({"id": case["id"], "model": args.model, "prediction": pred, "raw": text,
                                  "usage": usage, "seconds": round(time.time() - start, 2)}) + "\n")
            out.flush()
            print("%-12s %-28s gold=%s" % (case["id"], pred["decision"] if pred else "UNPARSEABLE",
                                           case["gold"]["decision"]))


if __name__ == "__main__":
    main()
