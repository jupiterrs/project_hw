"""Filter ScaleSWE task instances to only those with available Docker images.

Some aweaiteam/scaleswe:<instance_id> images were never published to Docker Hub.
This script checks each image and writes a JSONL with only the available ones,
so AweAgent doesn't waste 3 retries on missing images.

Usage:
    python filter_available_images.py \\
        --input /public/lianghong/nurdaulet_absattarov/data/task_instances/processed_to_upload.jsonl \\
        --output /public/lianghong/nurdaulet_absattarov/data/task_instances/available_images.jsonl
"""

import json
import subprocess
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


def check_image_exists(image_tag: str) -> bool:
    """Check if a Docker image exists on Docker Hub via manifest inspect."""
    try:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image_tag],
            capture_output=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input JSONL")
    parser.add_argument("--output", required=True, help="Output JSONL (only available)")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    instances = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            instances.append(json.loads(line))

    print(f"Loaded {len(instances)} instances. Checking images in parallel...")

    available = []
    missing = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(check_image_exists, f"aweaiteam/scaleswe:{r['instance_id']}"): r
            for r in instances
        }
        for i, future in enumerate(as_completed(futures), 1):
            r = futures[future]
            if future.result():
                available.append(r)
            else:
                missing.append(r["instance_id"])
            if i % 50 == 0:
                print(f"  Checked {i}/{len(instances)} — {len(available)} available, {len(missing)} missing")

    with open(args.output, "w") as f:
        for r in available:
            f.write(json.dumps(r) + "\n")

    missing_path = str(Path(args.output).with_suffix(".missing.txt"))
    with open(missing_path, "w") as f:
        for iid in missing:
            f.write(iid + "\n")

    print(f"\nTotal: {len(instances)}")
    print(f"Available: {len(available)}  → {args.output}")
    print(f"Missing: {len(missing)}  → {missing_path}")


if __name__ == "__main__":
    main()