import re
import os
import sys
import subprocess
import json
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sft-data")
SANDBOX_PATH = os.path.join(DATA_DIR, "sandbox.py")


def normalizer(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def validate_code_blocks(code_blocks: list, obs_blocks: list) -> dict:
    """Run each code block and compare output to its observation."""
    stats = {"total": len(code_blocks), "matches": 0, "fixes": 0, "crashes": 0}

    if len(code_blocks) != len(obs_blocks):
        stats["mismatch"] = True
        return stats

    for i, code in enumerate(code_blocks):
        with open(SANDBOX_PATH, "w") as f:
            f.write(code)

        try:
            result = subprocess.run(
                [sys.executable, SANDBOX_PATH],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            stats["crashes"] += 1
            print(f"    Block {i}: TIMEOUT")
            continue

        if result.returncode != 0:
            stats["crashes"] += 1
            print(f"    Block {i}: CRASH - {result.stderr.strip()[:100]}")
            continue

        cleaned_result = normalizer(result.stdout)
        cleaned_obs = normalizer(obs_blocks[i])

        if cleaned_result == cleaned_obs:
            stats["matches"] += 1
            print(f"    Block {i}: MATCH")
        else:
            stats["fixes"] += 1
            print(f"    Block {i}: MISMATCH")
            print(f"      Expected: {cleaned_obs[:80]}...")
            print(f"      Got:      {cleaned_result[:80]}...")

    # Clean up sandbox
    if os.path.exists(SANDBOX_PATH):
        os.remove(SANDBOX_PATH)

    return stats


def validate_markdown(filepath: str) -> dict:
    """Validate a readable markdown trajectory file."""
    with open(filepath, "r") as f:
        text = f.read()

    code_blocks = re.findall(
        r"<tool>\s*```\s*python(.*?)\s*```\s*</tool>", text, re.DOTALL
    )
    obs_blocks = re.findall(r"<observation>\s*(.*?)\s*</observation>", text, re.DOTALL)

    print(
        f"  Found {len(code_blocks)} code blocks, {len(obs_blocks)} observation blocks"
    )
    return validate_code_blocks(code_blocks, obs_blocks)


def validate_jsonl(filepath: str) -> dict:
    """Validate a JSONL trajectory file."""
    total_stats = {"total": 0, "matches": 0, "fixes": 0, "crashes": 0}

    with open(filepath, "r") as f:
        for line_num, line in enumerate(f, 1):
            record = json.loads(line)
            messages = record.get("messages", record.get("conversations", []))

            # Normalize format (LlamaFactory uses "conversations"/"from"/"value")
            all_code = []
            all_obs = []
            for msg in messages:
                if isinstance(msg, dict):
                    content = msg.get("content", msg.get("value", ""))
                else:
                    continue

                code_blocks = re.findall(
                    r"<tool>\s*```\s*python(.*?)\s*```\s*</tool>", content, re.DOTALL
                )
                obs_blocks = re.findall(
                    r"<observation>\s*(.*?)\s*</observation>", content, re.DOTALL
                )
                all_code.extend(code_blocks)
                all_obs.extend(obs_blocks)

            if all_code or all_obs:
                print(
                    f"  Record {line_num}: {len(all_code)} code blocks, {len(all_obs)} observations"
                )
                stats = validate_code_blocks(all_code, all_obs)
                for key in ["total", "matches", "fixes", "crashes"]:
                    total_stats[key] += stats.get(key, 0)

    return total_stats


def main():
    parser = argparse.ArgumentParser(description="Validate trajectory data files")
    parser.add_argument("--dir", type=str, default=DATA_DIR, help="Directory to scan")
    parser.add_argument("--file", type=str, help="Validate a single file")
    args = parser.parse_args()

    if args.file:
        files = [args.file]
    else:
        scan_dir = args.dir
        files = sorted(
            os.path.join(scan_dir, f)
            for f in os.listdir(scan_dir)
            if f.endswith(".md") or f.endswith(".jsonl")
        )

    # Filter to trajectory files only (skip example/reference files)
    trajectory_files = []
    for f in files:
        basename = os.path.basename(f)
        if "trajectory" in basename or "traj" in basename:
            trajectory_files.append(f)

    if not trajectory_files:
        print("No trajectory files found!")
        return

    print(f"Validating {len(trajectory_files)} trajectory files\n")

    grand_total = {"total": 0, "matches": 0, "fixes": 0, "crashes": 0}

    for filepath in trajectory_files:
        basename = os.path.basename(filepath)
        print(f"\n{'=' * 50}")
        print(f"File: {basename}")
        print(f"{'=' * 50}")

        if filepath.endswith(".md"):
            stats = validate_markdown(filepath)
        elif filepath.endswith(".jsonl"):
            stats = validate_jsonl(filepath)
        else:
            continue

        for key in ["total", "matches", "fixes", "crashes"]:
            grand_total[key] += stats.get(key, 0)

    # Grand summary
    print(f"\n{'=' * 50}")
    print("GRAND SUMMARY")
    print(f"{'=' * 50}")
    print(f"Total code blocks:  {grand_total['total']}")
    print(f"Matches:            {grand_total['matches']}")
    print(f"Mismatches:         {grand_total['fixes']}")
    print(f"Crashes:            {grand_total['crashes']}")
    if grand_total["total"]:
        rate = grand_total["matches"] / grand_total["total"] * 100
        print(f"Validation rate:    {rate:.1f}%")


if __name__ == "__main__":
    main()
