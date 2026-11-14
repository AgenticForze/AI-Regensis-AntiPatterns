"""CI cost gate: fail a pull request whose cost per successful task rises more than the allowed amount.

Input files are eval-run outputs, one JSON object per case:
  {"id": "case-17", "success": true, "cost_usd": 0.0123, "calls": 3}

Usage:
  python cost_gate.py baseline.jsonl candidate.jsonl --max-increase 0.15
  Set COST_INCREASE_APPROVED=true (e.g. from a PR label applied by the budget owner) to pass anyway.
"""
import argparse
import json
import os
import sys


def load(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def summary(rows):
    wins = sum(r["success"] for r in rows)
    cost = sum(r["cost_usd"] for r in rows)
    return {"cases": len(rows), "success_rate": wins / len(rows), "cost_total": cost,
            "cost_per_success": cost / wins if wins else float("inf"),
            "max_calls_per_case": max(r.get("calls", 1) for r in rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline"); ap.add_argument("candidate")
    ap.add_argument("--max-increase", type=float, default=0.15)
    ap.add_argument("--max-calls-per-case", type=int, default=6)
    a = ap.parse_args()
    b, c = summary(load(a.baseline)), summary(load(a.candidate))
    delta = c["cost_per_success"] / b["cost_per_success"] - 1
    print(f"cost per successful task: {b['cost_per_success']:.4f} -> {c['cost_per_success']:.4f} ({delta:+.0%})")
    print(f"success rate: {b['success_rate']:.1%} -> {c['success_rate']:.1%}; "
          f"max calls per case: {c['max_calls_per_case']}")
    approved = os.getenv("COST_INCREASE_APPROVED", "").lower() == "true"
    failures = []
    if delta > a.max_increase and not approved:
        failures.append(f"cost per successful task up {delta:.0%} (limit {a.max_increase:.0%}); needs budget-owner approval")
    if c["max_calls_per_case"] > a.max_calls_per_case:
        failures.append(f"a case made {c['max_calls_per_case']} model calls (limit {a.max_calls_per_case})")
    if failures:
        print("COST GATE FAILED:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print("cost gate passed")


if __name__ == "__main__":
    main()
