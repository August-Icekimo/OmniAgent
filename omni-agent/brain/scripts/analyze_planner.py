#!/usr/bin/env python3
import sys
import json
import statistics
import argparse
import contextlib
from typing import List, Dict, Any

def calculate_percentiles(data: List[float]) -> Dict[str, float]:
    if not data:
        return {"p50": 0.0, "p95": 0.0}
    if len(data) == 1:
        return {"p50": data[0], "p95": data[0]}
    p50 = statistics.median(data)
    p95 = statistics.quantiles(data, n=20)[-1]  # interpolated 95th percentile
    return {"p50": p50, "p95": p95}

def main():
    parser = argparse.ArgumentParser(description="Analyze planner timing logs.")
    parser.add_argument("file", nargs="?", help="Log file to analyze (defaults to stdin)")
    parser.add_argument("--min-samples", type=int, default=15, help="Minimum steady-state samples for reliable stats")
    args = parser.parse_args()

    steady_state = []
    cold_starts = []
    skipped_lines = 0
    total_lines = 0

    span_keys = [
        "plan_graph_entry_ms",
        "plan_routing_ms",
        "plan_complexity_prompt_ms",
        "plan_complexity_llm_ms",
        "plan_complexity_parse_ms",
        "plan_upgrade_check_ms",
        "plan_skills_prompt_ms",
        "plan_main_llm_ms",
        "plan_skill_parse_ms",
        "total_ms",
    ]

    steady_spans = {key: [] for key in span_keys}

    input_cm = open(args.file) if args.file else contextlib.nullcontext(sys.stdin)
    with input_cm as input_source:
        for line in input_source:
            total_lines += 1
            data = None
            line = line.strip()
            if not line:
                continue

            # Fast path: brain logger emits msg as a raw (unescaped) JSON object,
            # making the outer wrapper invalid JSON.  The line ends with `}"}`:
            #   inner-JSON-close `}` → msg-quote-close `"` → outer-JSON-close `}`
            # Search for the inner record directly and find its real close brace.
            for marker in ('{"event": "planner_timing"', '{"event":"planner_timing"'):
                pt_start = line.find(marker)
                if pt_start != -1:
                    # Try to find the inner JSON close: pattern `}"}` marks end of msg value
                    inner_close = line.rfind('}"')
                    if inner_close > pt_start:
                        pt_end = inner_close  # `}` sits at inner_close, `"` at inner_close+1
                    else:
                        pt_end = line.rfind("}")
                    if pt_end > pt_start:
                        try:
                            data = json.loads(line[pt_start:pt_end + 1])
                        except json.JSONDecodeError:
                            pass
                    break

            # Fallback: try outer JSON → msg field
            if data is None:
                start_idx = line.find("{")
                if start_idx != -1:
                    try:
                        end_idx = line.rfind("}")
                        parsed = json.loads(line[start_idx:end_idx + 1])
                        if isinstance(parsed, dict):
                            if "msg" in parsed:
                                msg_content = parsed["msg"]
                                if isinstance(msg_content, str) and "{" in msg_content:
                                    m_start = msg_content.find("{")
                                    m_end = msg_content.rfind("}")
                                    try:
                                        data = json.loads(msg_content[m_start:m_end + 1])
                                    except json.JSONDecodeError:
                                        data = parsed
                                else:
                                    data = parsed
                            else:
                                data = parsed
                    except json.JSONDecodeError:
                        pass

            if not data or not isinstance(data, dict) or data.get("event") != "planner_timing":
                skipped_lines += 1
                continue

            is_cold = data.get("is_cold_start", False)
            if is_cold:
                cold_starts.append(data)
            else:
                steady_state.append(data)
                for key in span_keys:
                    if key in data:
                        steady_spans[key].append(data[key])

    print(f"--- Planner Timing Analysis ---")
    print(f"Total lines processed: {total_lines}")
    print(f"Steady-state samples: {len(steady_state)}")
    print(f"Cold-start samples: {len(cold_starts)}")
    print(f"Skipped lines: {skipped_lines}")
    print()

    if len(steady_state) < args.min_samples:
        print(f"WARNING: Fewer than {args.min_samples} steady-state samples. Percentiles may be unreliable.")
        print()

    if steady_state:
        print(f"{'Span':<25} | {'p50 (ms)':>10} | {'p95 (ms)':>10}")
        print("-" * 51)
        for key in span_keys:
            stats = calculate_percentiles(steady_spans[key])
            print(f"{key:<25} | {stats['p50']:>10.2f} | {stats['p95']:>10.2f}")
    else:
        print("No steady-state data found.")

    if cold_starts:
        print("\n--- Cold-start Details ---")
        print(f"{'Request ID':<36} | {'Total (ms)':>10} | {'Executor':<10}")
        print("-" * 60)
        for cs in cold_starts:
            print(f"{cs.get('request_id', 'N/A'):<36} | {cs.get('total_ms', 0.0):>10.2f} | {cs.get('executor_chosen', 'N/A'):<10}")

if __name__ == "__main__":
    main()
