#!/usr/bin/env python3
import sys
import json
import statistics
import argparse
from typing import List, Dict, Any

def calculate_percentiles(data: List[float]) -> Dict[str, float]:
    if not data:
        return {"p50": 0.0, "p95": 0.0}
    if len(data) == 1:
        return {"p50": data[0], "p95": data[0]}

    sorted_data = sorted(data)
    p50 = statistics.median(sorted_data)

    # Simple p95 implementation
    idx = int(0.95 * len(sorted_data))
    p95 = sorted_data[min(idx, len(sorted_data) - 1)]

    return {"p50": p50, "p95": p95}

def main():
    parser = argparse.ArgumentParser(description="Analyze planner timing logs.")
    parser.add_argument("file", nargs="?", help="Log file to analyze (defaults to stdin)")
    parser.add_argument("--min-samples", type=int, default=15, help="Minimum steady-state samples for reliable stats")
    args = parser.parse_args()

    input_source = open(args.file, "r") if args.file else sys.stdin

    steady_state = []
    cold_starts = []
    skipped_lines = 0
    total_lines = 0

    span_keys = [
        "plan_graph_entry_ms",
        "plan_config_load_ms",
        "plan_prompt_build_ms",
        "plan_llm_call_ms",
        "plan_decision_parse_ms",
        "total_ms"
    ]

    # Structure to hold span values for steady state
    steady_spans = {key: [] for key in span_keys}

    try:
        for line in input_source:
            total_lines += 1
            data = None
            line = line.strip()
            if not line:
                continue

            # Find the first { and last } to extract JSON block
            start_idx = line.find("{")
            if start_idx != -1:
                try:
                    end_idx = line.rfind("}")
                    parsed = json.loads(line[start_idx:end_idx+1])
                    if isinstance(parsed, dict):
                        # If the log entry has a 'msg' field, it might contain the actual JSON record
                        if "msg" in parsed:
                            msg_content = parsed["msg"]
                            if isinstance(msg_content, str) and "{" in msg_content:
                                m_start = msg_content.find("{")
                                m_end = msg_content.rfind("}")
                                try:
                                    data = json.loads(msg_content[m_start:m_end+1])
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

    finally:
        if input_source is not sys.stdin:
            input_source.close()

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
