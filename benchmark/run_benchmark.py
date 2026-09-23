"""Run the 60-reply test set through each setup and write results.json.

Usage (from repo root):
    export NEBIUS_API_KEY=...
    export ANTHROPIC_API_KEY=...   # optional closed-model baseline
    python benchmark/run_benchmark.py
"""
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import llm  # noqa: E402

HERE = os.path.dirname(__file__)
DATA = json.load(open(os.path.join(HERE, "testset.json"), encoding="utf-8"))
START, END = DATA["shift"]["start"], DATA["shift"]["end"]

# Closed-model baselines: (model id, $/1M input, $/1M output). Failing ones are skipped.
CLAUDE_BASELINES = [
    ("claude-haiku-4-5-20251001", 1.00, 5.00),
    ("claude-sonnet-4-6", 3.00, 15.00),
]


def claude_call(model, pin, pout, message):
    import anthropic
    c = anthropic.Anthropic()
    t0 = time.perf_counter()
    resp = c.messages.create(
        model=model, max_tokens=300,
        system=llm.SYSTEM_PROMPT.replace("Reasoning: low\n\n", "").format(start=START, end=END),
        messages=[{"role": "user", "content": message}],
    )
    latency = time.perf_counter() - t0
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    parsed = llm.extract_json(text)
    cost = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1_000_000
    return {"parsed": parsed if llm.is_valid(parsed) else None, "raw": text,
            "latency_s": latency, "cost_usd": cost, "escalated": False}


def with_retry(fn, *args):
    for attempt in range(3):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                return {"parsed": None, "raw": f"ERROR: {e}", "latency_s": 0.0, "cost_usd": 0.0, "escalated": False, "error": True}
            time.sleep(2 * (attempt + 1))


def correct(parsed, gold):
    if not parsed or parsed["status"] != gold["status"]:
        return False, False
    if gold["status"] == "partial":
        return parsed.get("from") == gold["from"] and parsed.get("until") == gold["until"], True
    return True, True


def run_setup(name, fn):
    items = DATA["items"]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda it: with_retry(fn, it["message"]), items))
    errors_api = sum(1 for r in results if r.get("error"))
    if errors_api == len(items):
        print(f"  !! {name}: every call failed, skipping. First error: {results[0]['raw'][:200]}")
        return None, None
    full = status = 0
    wrong = []
    for it, r in zip(items, results):
        ok, ok_status = correct(r["parsed"], it["gold"])
        full += ok
        status += ok_status
        if not ok:
            wrong.append({"id": it["id"], "message": it["message"], "gold": it["gold"], "got": r["parsed"] or r["raw"][:200]})
    n = len(items)
    lat = [r["latency_s"] for r in results if not r.get("error")]
    summary = {
        "setup": name,
        "accuracy": full / n,
        "status_accuracy": status / n,
        "median_latency_s": statistics.median(lat) if lat else 0,
        "cost_per_1000": sum(r["cost_usd"] for r in results) / n * 1000,
        "escalation_rate": (sum(1 for r in results if r.get("escalated")) / n) if name.startswith("Cascade") else None,
        "api_errors": errors_api,
    }
    print(f"  {name}: acc {summary['accuracy']*100:.1f}% | status {summary['status_accuracy']*100:.1f}% | "
          f"median {summary['median_latency_s']:.2f}s | ${summary['cost_per_1000']:.4f}/1k | api errors {errors_api}")
    return summary, wrong


def main():
    setups = [
        ("Qwen3-30B-A3B (open, small)", lambda m: llm.parse_reply(m, START, END, mode="small")),
        ("gpt-oss-120b (open, large)", lambda m: llm.parse_reply(m, START, END, mode="big")),
        ("Cascade Qwen3-30B → gpt-oss-120b (Onyx)", lambda m: llm.parse_reply(m, START, END, mode="cascade")),
    ]
    if os.environ.get("ANTHROPIC_API_KEY"):
        for model, pin, pout in CLAUDE_BASELINES:
            setups.append((f"{model} (closed baseline)", lambda m, a=model, b=pin, c=pout: claude_call(a, b, c, m)))
    else:
        print("ANTHROPIC_API_KEY not set - running open models only.")

    out = {"n": len(DATA["items"]), "summary": [], "errors": {}}
    for name, fn in setups:
        print(f"Running {name} ...")
        summary, wrong = run_setup(name, fn)
        if summary:
            out["summary"].append(summary)
            out["errors"][name] = wrong
            if name.startswith("Cascade"):
                out["cascade_errors"] = wrong
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nSaved benchmark/results.json")


if __name__ == "__main__":
    main()
