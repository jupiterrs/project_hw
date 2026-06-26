"""Aggregate success rate across all trajectory files in a directory.

Counts UNIQUE instances only — if an instance_id appears in multiple run
subdirs (e.g., retried), only the latest attempt is counted.
"""

import json
import sys
import argparse
import glob
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Aggregate success rate across all trajectory files")
    parser.add_argument("--dir", required=True, help="Directory containing run subdirs with trajectories.jsonl")
    args = parser.parse_args()

    # Map instance_id -> (success_bool, source_file)
    # Later files (sorted) overwrite earlier ones — keeps latest attempt
    instances = {}

    files_seen = []
    for fpath in sorted(glob.glob(str(Path(args.dir) / "*" / "trajectories.jsonl"))):
        files_seen.append(fpath)
        file_total = 0
        file_success = 0
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                iid = r.get("instance_id")
                if iid is None:
                    continue
                file_total += 1
                if r.get("success"):
                    file_success += 1
                # Always overwrite — sorted order means later = more recent
                instances[iid] = (bool(r.get("success")), fpath)
        print(f"  {Path(fpath).parent.name}: {file_success}/{file_total} ({file_success/file_total*100:.1f}%)")

    # Count unique instances
    total = len(instances)
    success = sum(1 for s, _ in instances.values() if s)

    print()
    pct = success / total * 100 if total else 0
    print(f"{'='*50}")
    print(f"  Aggregated across {len(files_seen)} run(s)")
    print(f"  Unique instances: {total}  Success: {success}  Rate: {pct:.1f}%")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()