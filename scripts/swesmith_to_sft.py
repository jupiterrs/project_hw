"""Convert SWE-smith trajectories to LlamaFactory SFT format.

Takes first N resolved trajectories from train parquet shards,
outputs ShareGPT-format JSONL for LlamaFactory training.
"""

import json
import sys
import argparse
import glob
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Convert SWE-smith to SFT format")
    parser.add_argument("--input-dir", required=True, help="Directory with train-*.parquet files")
    parser.add_argument("--output", required=True, help="Output train.jsonl")
    parser.add_argument("--num", type=int, default=2000, help="Number of trajectories to take")
    parser.add_argument("--resolved-only", action="store_true", default=True, help="Only keep resolved trajectories")
    args = parser.parse_args()

    import pyarrow.parquet as pq

    files = sorted(glob.glob(str(Path(args.input_dir) / "train-*.parquet")))
    if not files:
        print(f"No train-*.parquet files found in {args.input_dir}")
        sys.exit(1)

    print(f"Found {len(files)} parquet shards")

    collected = []
    total_loaded = 0
    resolved_count = 0

    for fpath in files:
        if len(collected) >= args.num:
            break
        print(f"  Loading {Path(fpath).name}...")
        table = pq.read_table(fpath)
        records = table.to_pylist()
        total_loaded += len(records)

        for rec in records:
            if len(collected) >= args.num:
                break
            if args.resolved_only and not rec.get("resolved"):
                continue
            resolved_count += 1

            messages = rec.get("messages", [])
            if not messages:
                continue

            # Keep only messages field — LF only needs this
            collected.append({"messages": messages})

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w") as f:
        for item in collected:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    print(f"\nDone: {len(collected)} trajectories written to {args.output}")
    print(f"Total loaded: {total_loaded}, Resolved: {resolved_count}")
    if args.resolved_only:
        print(f"Resolved rate: {resolved_count/total_loaded*100:.1f}%")


if __name__ == "__main__":
    main()