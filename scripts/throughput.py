"""Analyze trajectory generation throughput."""

import json
import sys
import argparse
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Trajectory throughput analysis")
    parser.add_argument("--input", required=True, help="trajectories.jsonl")
    parser.add_argument("--concurrent", type=int, default=8, help="Number of concurrent instances")
    parser.add_argument("--target", type=int, default=2000, help="Target number of SUCCESSFUL trajectories")
    args = parser.parse_args()

    durations = []
    total_prompt_tokens = 0
    total_comp_tokens = 0
    success_count = 0
    fail_count = 0

    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            d = r.get("duration")
            if d:
                durations.append(d)
            s = r.get("stats") or {}
            total_prompt_tokens += s.get("total_prompt_tokens", 0)
            total_comp_tokens += s.get("total_completion_tokens", 0)
            if r.get("success"):
                success_count += 1
            else:
                fail_count += 1

    total = success_count + fail_count
    if not durations:
        print("No completed trajectories found")
        return

    sorted_dur = sorted(durations)
    avg_dur = sum(durations) / len(durations)
    min_dur = min(durations)
    max_dur = max(durations)
    median_dur = sorted_dur[len(sorted_dur) // 2]
    p90_dur = sorted_dur[int(len(sorted_dur) * 0.9)]
    p95_dur = sorted_dur[int(len(sorted_dur) * 0.95)]
    over_30min = sum(1 for d in durations if d > 1800)
    over_1hr = sum(1 for d in durations if d > 3600)
    total_time_hrs = sum(durations) / 3600
    per_hour = len(durations) / total_time_hrs if total_time_hrs > 0 else 0

    # Per success/fail breakdown
    success_dur = []
    fail_dur = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            d = r.get("duration", 0)
            if r.get("success"):
                success_dur.append(d)
            else:
                fail_dur.append(d)

    print(f"{'='*50}")
    print(f"   Trajectory Throughput Report")
    print(f"{'='*50}")
    print(f"  Completed:          {total}")
    print(f"  Success / Fail:     {success_count} / {fail_count}")
    print(f"  Success rate:       {success_count/total*100:.1f}%")
    print(f"")
    print(f"  --- Duration ---")
    print(f"  Avg:                {avg_dur:.0f}s ({avg_dur/60:.1f} min)")
    print(f"  Median:             {median_dur:.0f}s ({median_dur/60:.1f} min)")
    print(f"  P90:                {p90_dur:.0f}s ({p90_dur/60:.1f} min)")
    print(f"  P95:                {p95_dur:.0f}s ({p95_dur/60:.1f} min)")
    print(f"  Min:                {min_dur:.0f}s ({min_dur/60:.1f} min)")
    print(f"  Max:                {max_dur:.0f}s ({max_dur/60:.1f} min)")
    print(f"  Over 30 min:        {over_30min} ({over_30min/total*100:.1f}%)")
    print(f"  Over 1 hr:          {over_1hr} ({over_1hr/total*100:.1f}%)")
    print(f"")
    print(f"  --- By Outcome ---")
    if success_dur:
        avg_s = sum(success_dur) / len(success_dur)
        print(f"  Success avg:        {avg_s:.0f}s ({avg_s/60:.1f} min)")
    if fail_dur:
        avg_f = sum(fail_dur) / len(fail_dur)
        print(f"  Fail avg:           {avg_f:.0f}s ({avg_f/60:.1f} min)")
    print(f"")
    print(f"  --- Throughput ---")
    print(f"  Sum of durations:   {total_time_hrs:.1f} hrs")
    print(f"  Concurrent:         {args.concurrent}")
    wall_clock_hrs = total_time_hrs / args.concurrent
    print(f"  Est. wall-clock:    {wall_clock_hrs:.1f} hrs ({wall_clock_hrs/24:.1f} days)")
    effective_per_hour = len(durations) / wall_clock_hrs if wall_clock_hrs > 0 else 0
    print(f"  Effective traj/hr:  {effective_per_hour:.1f}")
    print(f"")
    print(f"  --- Tokens ---")
    print(f"  Total:              {total_prompt_tokens + total_comp_tokens:,}")
    print(f"    Prompt:           {total_prompt_tokens:,}")
    print(f"    Completion:       {total_comp_tokens:,}")
    print(f"{'='*50}")
    print(f"")
    success_rate = success_count / total if total > 0 else 0
    total_needed = int(args.target / success_rate) if success_rate > 0 else 0
    est_wall_hrs = total_needed / effective_per_hour if effective_per_hour > 0 else 0
    print(f"  --- Estimate ---")
    print(f"  Target successful:  {args.target:,}")
    print(f"  Total needed:       ~{total_needed:,} (at {success_rate*100:.1f}% success)")
    print(f"  Est. wall-clock:    {est_wall_hrs:.0f} hrs ({est_wall_hrs/24:.1f} days)")
    print(f"  At {effective_per_hour:.1f} traj/hr with {args.concurrent} concurrent")


if __name__ == "__main__":
    main()