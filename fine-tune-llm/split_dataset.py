"""Split all trajectory JSONL files into train/val/test sets.

Split: 80% train / 10% val / 10% test
Strategy: Random shuffle with a fixed seed, then split.
Outputs: sft-data/train.jsonl, sft-data/val.jsonl, sft-data/test.jsonl
"""
import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).parent / "sft-data"
SEED = 42
TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
# TEST_RATIO = 0.1 (remainder)

def main():
    all_trajectories = []

    for jsonl_file in sorted(DATA_DIR.glob("*_trajectories.jsonl")):
        with open(jsonl_file, "r") as f:
            for line in f:
                data = json.loads(line)
                all_trajectories.append(data)

    print(f"Total trajectories: {len(all_trajectories)}")

    random.seed(SEED)
    random.shuffle(all_trajectories)

    n = len(all_trajectories)
    train_end = int(n * TRAIN_RATIO)
    val_end = train_end + int(n * VAL_RATIO)

    train = all_trajectories[:train_end]
    val = all_trajectories[train_end:val_end]
    test = all_trajectories[val_end:]

    print(f"Train: {len(train)}")
    print(f"Val:   {len(val)}")
    print(f"Test:  {len(test)}")

    for split_name, split_data in [("train", train), ("val", val), ("test", test)]:
        output_path = DATA_DIR / f"{split_name}.jsonl"
        with open(output_path, "w") as f:
            for entry in split_data:
                f.write(json.dumps(entry) + "\n")
        print(f"Wrote {output_path}")

if __name__ == "__main__":
    main()