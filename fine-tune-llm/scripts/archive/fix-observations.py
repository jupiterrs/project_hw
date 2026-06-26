import re
import os
import sys
import subprocess
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sft-data")
READABLE_MD = os.path.join(DATA_DIR, "aime_2005_trajectories_readable.md")
JSONL_FILE = os.path.join(DATA_DIR, "aime_2005_trajectories.jsonl")
SANDBOX_PATH = os.path.join(DATA_DIR, "sandbox.py")


def normalizer(text: str):
    return re.sub(r"\s+", " ", text.strip())


# Step 1: Fix the readable markdown
with open(READABLE_MD, "r") as f:
    md_text = f.read()

# Extract all code blocks and their positions
code_blocks = re.findall(
    r"<tool>\s*```\s*python(.*?)\s*```\s*</tool>", md_text, re.DOTALL
)

# Extract all observation blocks
obs_blocks = re.findall(
    r"<observation>\s*(.*?)\s*</observation>", md_text, re.DOTALL
)

print(f"Found {len(code_blocks)} code blocks and {len(obs_blocks)} observation blocks")

# Run each code block and collect real output
real_outputs = []
for i, code in enumerate(code_blocks):
    with open(SANDBOX_PATH, "w") as f:
        f.write(code)

    result = subprocess.run(
        [sys.executable, SANDBOX_PATH],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode == 0:
        real_output = result.stdout.strip()
        real_outputs.append(real_output)
        matches = normalizer(real_output) == normalizer(obs_blocks[i])
        print(f"Block {i}: {'MATCH' if matches else 'MISMATCH'}")
        if not matches:
            print(f"  OLD obs: {normalizer(obs_blocks[i])[:80]}...")
            print(f"  NEW out: {normalizer(real_output)[:80]}...")
    else:
        print(f"Block {i}: CRASH - {result.stderr.strip()[:100]}")
        real_outputs.append(obs_blocks[i])  # keep original if code crashes

# Replace observation blocks in markdown
def replace_observation(match):
    idx = replace_observation.counter
    replace_observation.counter += 1
    if idx < len(real_outputs):
        return f"<observation>\n{real_outputs[idx]}\n</observation>"
    return match.group(0)

replace_observation.counter = 0

new_md_text = re.sub(
    r"<observation>\s*.*?\s*</observation>",
    replace_observation,
    md_text,
    flags=re.DOTALL,
)

with open(READABLE_MD, "w") as f:
    f.write(new_md_text)

print(f"\nUpdated {READABLE_MD}")


# Step 2: Fix the JSONL file
with open(JSONL_FILE, "r") as f:
    lines = f.readlines()

jsonl_data = [json.loads(line) for line in lines]
code_idx = 0

for entry in jsonl_data:
    for msg in entry["messages"]:
        if msg["role"] != "assistant":
            continue
        content = msg["content"]

        # Find all code blocks in this message
        msg_code_blocks = re.findall(
            r"<tool>\s*```\s*python(.*?)\s*```\s*</tool>", content, re.DOTALL
        )

        # Find all observation blocks in this message
        msg_obs_blocks = re.findall(
            r"<observation>\s*(.*?)\s*</observation>", content, re.DOTALL
        )

        if not msg_obs_blocks:
            continue

        # Run each code block and replace observations
        for j, code in enumerate(msg_code_blocks):
            with open(SANDBOX_PATH, "w") as f:
                f.write(code)

            result = subprocess.run(
                [sys.executable, SANDBOX_PATH],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                real_output = result.stdout.strip()
                # Replace this specific observation in the content
                old_obs = msg_obs_blocks[j]
                content = content.replace(
                    f"<observation>{old_obs}</observation>",
                    f"<observation>\n{real_output}\n</observation>",
                    1,
                )

        msg["content"] = content

with open(JSONL_FILE, "w") as f:
    for entry in jsonl_data:
        f.write(json.dumps(entry) + "\n")

print(f"Updated {JSONL_FILE}")

# Clean up sandbox
if os.path.exists(SANDBOX_PATH):
    os.remove(SANDBOX_PATH)
    print("Cleaned up sandbox.py")