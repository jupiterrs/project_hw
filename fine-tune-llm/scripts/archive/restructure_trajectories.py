import re
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "sft-data"
INPUT_JSONL = DATA_DIR / "aime_2005_trajectories.jsonl"
OUTPUT_JSONL = DATA_DIR / "aime_2005_trajectories_multiturn.jsonl"

SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."


def split_trajectory(content: str) -> list[dict]:
    """Split a single-turn trajectory into multi-turn messages.

    The model should learn to:
    1. Output reasoning + <tool>...</tool> then STOP
    2. Receive <observation>...</observation> from harness
    3. Either output more <tool> blocks or <answer>...</answer>

    Pattern: reasoning -> <tool>code</tool> -> <observation>output</observation> -> ... -> <answer>ans</answer>
    """
    messages = []

    # Split the content into segments by <tool>, <observation>, and <answer> tags
    # We use finditer to get positions and split accordingly
    pattern = re.compile(
        r'<tool>\s*```\s*python(.*?)```\s*</tool>'
        r'|<observation>\s*(.*?)\s*</observation>'
        r'|<answer>\s*(.*?)\s*</answer>',
        re.DOTALL
    )

    # Collect all matches with their positions
    matches = list(pattern.finditer(content))

    if not matches:
        # No tags at all — just a text response
        messages.append({"role": "assistant", "content": content.strip()})
        return messages

    pos = 0
    i = 0

    while i < len(matches):
        match = matches[i]
        # Text before this match (reasoning)
        before_text = content[pos:match.start()].strip()

        if match.group(1) is not None:
            # This is a <tool> block
            code = match.group(1).strip()

            # Build assistant message: reasoning + <tool> block
            assistant_parts = []
            if before_text:
                assistant_parts.append(before_text)
            assistant_parts.append(f"<tool>\n```python\n{code}\n```\n</tool>")
            assistant_content = "\n\n".join(assistant_parts)

            messages.append({"role": "assistant", "content": assistant_content})

            # Next should be <observation> — it becomes the user message
            if i + 1 < len(matches) and matches[i + 1].group(2) is not None:
                obs_match = matches[i + 1]
                obs_text = obs_match.group(2).strip()
                messages.append({
                    "role": "user",
                    "content": f"<observation>\n{obs_text}\n</observation>"
                })
                pos = obs_match.end()
                i += 2
            else:
                # No observation after tool — skip (shouldn't happen)
                pos = match.end()
                i += 1

        elif match.group(3) is not None:
            # This is an <answer> block
            answer = match.group(3).strip()

            # Build assistant message: reasoning + <answer> block
            assistant_parts = []
            if before_text:
                assistant_parts.append(before_text)
            assistant_parts.append(f"<answer>\n{answer}\n</answer>")
            assistant_content = "\n\n".join(assistant_parts)

            messages.append({"role": "assistant", "content": assistant_content})
            pos = match.end()
            i += 1

        elif match.group(2) is not None:
            # Stray <observation> without preceding <tool> — shouldn't happen
            # Skip it
            pos = match.end()
            i += 1

        else:
            pos = match.end()
            i += 1

    # Handle any remaining text after the last match
    remaining = content[pos:].strip()
    if remaining:
        # Append to last assistant message
        if messages and messages[-1]["role"] == "assistant":
            messages[-1]["content"] += "\n\n" + remaining
        else:
            messages.append({"role": "assistant", "content": remaining})

    return messages


def restructure_entry(entry: dict) -> dict:
    """Convert a single-turn entry to multi-turn format."""
    system_msg = {"role": "system", "content": SYSTEM_PROMPT}

    # Find the user message (the problem)
    user_msg = None
    assistant_content = None
    for msg in entry["messages"]:
        if msg["role"] == "user":
            user_msg = {"role": "user", "content": msg["content"]}
        elif msg["role"] == "assistant":
            assistant_content = msg["content"]

    if not user_msg or not assistant_content:
        return None

    # Split the assistant trajectory into turns
    turns = split_trajectory(assistant_content)

    # Build multi-turn messages
    messages = [system_msg, user_msg]
    for turn in turns:
        messages.append(turn)

    return {"messages": messages}


def main():
    with open(INPUT_JSONL, "r") as f:
        lines = f.readlines()

    data = [json.loads(l) for l in lines]

    restructured = []
    for i, entry in enumerate(data):
        result = restructure_entry(entry)
        if result:
            restructured.append(result)
            # Count turns
            turn_count = sum(1 for m in result["messages"] if m["role"] == "assistant")
            tool_count = sum(1 for m in result["messages"] if m["role"] == "assistant" and "<tool>" in m["content"])
            print(f"Problem {i+1}: {turn_count} assistant turns, {tool_count} with <tool>")
        else:
            print(f"Problem {i+1}: FAILED to restructure")

    with open(OUTPUT_JSONL, "w") as f:
        for entry in restructured:
            f.write(json.dumps(entry) + "\n")

    print(f"\nSaved {len(restructured)} multi-turn trajectories to {OUTPUT_JSONL}")


if __name__ == "__main__":
    main()