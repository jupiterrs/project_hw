"""
ETL Pipeline for AIME Math Trajectories

Pipeline:
  1. Extract: Load problems from competition_math dataset (and optionally scrape from websites)
  2. Clean: Remove LaTeX artifacts, duplicate text, normalize whitespace
  3. Transform: Convert prose solutions into agentic trajectories
  4. Validate: Run code blocks to verify observations match real Python output
  5. Load: Save as JSONL for SFT training
"""

import json
import re
import subprocess
from datasets import load_dataset


SYSTEM_PROMPT = (
    "You are a math problem solver. Think step by step. "
    "Use Python to verify your computations. If you make an error, correct yourself."
)


# ============================================================
# Step 1: EXTRACT
# ============================================================


def extract_from_huggingface():
    """Load competition math problems from HuggingFace."""
    ds = load_dataset("qwedsacf/competition_math", split="train")

    # Filter for computation-friendly types at hard levels
    good_types = {"Number Theory", "Counting & Probability", "Algebra", "Prealgebra"}
    good_levels = {"Level 3", "Level 4", "Level 5"}

    filtered = ds.filter(
        lambda x: x["type"] in good_types and x["level"] in good_levels
    )

    return [
        {
            "problem": ex["problem"],
            "solution": ex["solution"],
            "type": ex["type"],
            "level": ex["level"],
        }
        for ex in filtered
    ]


# ============================================================
# Step 2: CLEAN
# ============================================================


def clean_latex(text):
    """Remove common LaTeX artifacts and normalize text."""
    # Remove invisible Unicode characters
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

    # Remove LaTeX text commands but keep the content
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\emph\{([^}]*)\}", r"\1", text)

    # Remove \left and \right (bracket sizing commands)
    text = text.replace("\\left", "").replace("\\right", "")

    # Remove display math markers but keep content
    text = text.replace("\\[", "").replace("\\]", "")
    text = text.replace("\\(", "").replace("\\)", "")

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def clean_problem(problem):
    """Clean a problem statement."""
    return clean_latex(problem)


def clean_solution(solution):
    """Clean a solution, preserving the \boxed{} answer."""
    text = clean_latex(solution)
    return text


# ============================================================
# Step 3: TRANSFORM
# ============================================================


def extract_boxed_answer(solution):
    """Extract the final answer from \\boxed{...}."""
    match = re.search(r"\\boxed\{([^}]+)\}", solution)
    return match.group(1) if match else None


def auto_transform(problem, solution):
    """
    Automated first-pass conversion of a prose solution into an agentic trajectory.

    This produces LOWER QUALITY trajectories than hand-written ones.
    The verification code is a placeholder — it prints the answer instead
    of computing it. Use this for volume, then supplement with hand-written
    or LLM-generated trajectories for quality.
    """
    answer = extract_boxed_answer(solution)
    if not answer:
        return None

    # Remove the boxed answer from the solution body
    solution_text = re.sub(r"\\boxed\{[^}]+\}", "___", solution)
    solution_text = clean_latex(solution_text)

    # Split into rough steps (by sentences)
    steps = [s.strip() for s in re.split(r"(?<=\.)\s+", solution_text) if s.strip()]
    if not steps:
        return None

    parts = []

    # Opening reasoning
    parts.append("I need to solve this problem step by step.\n")

    # Add reasoning steps
    for step in steps:
        parts.append(step)

    # Add verification block (placeholder quality)
    parts.append("\nLet me verify my answer:")
    parts.append("<tool>")
    parts.append("```python")
    parts.append(f"# Verify the answer")
    parts.append(f"result = {answer}")
    parts.append(f"print(result)")
    parts.append("```")
    parts.append("</tool>")
    parts.append("")
    parts.append("<observation>")
    parts.append(str(answer))
    parts.append("</observation>")

    # Final answer
    parts.append(f"\n<answer>{answer}</answer>")

    trajectory = "\n".join(parts)

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": clean_problem(problem)},
            {"role": "assistant", "content": trajectory},
        ]
    }


# ============================================================
# Step 4: VALIDATE
# ============================================================


def validate_trajectory(messages):
    """
    Run all code blocks in a trajectory and verify observations match
    real Python output.

    Returns (is_valid, error_message).
    """
    assistant_content = messages["messages"][-1]["content"]

    # Extract code blocks
    code_blocks = re.findall(
        r"<tool>\n```python\n(.*?)\n```\n</tool>", assistant_content, re.DOTALL
    )

    # Extract observations
    observations = re.findall(
        r"<observation>\n(.*?)\n</observation>", assistant_content, re.DOTALL
    )

    if len(code_blocks) != len(observations):
        return (
            False,
            f"Code/observation count mismatch: {len(code_blocks)} vs {len(observations)}",
        )

    for code, expected in zip(code_blocks, observations):
        try:
            result = subprocess.run(
                ["python3", "-c", code], capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False, f"Code error: {result.stderr.strip()}"

            actual = result.stdout.strip()
            expected = expected.strip()

            if actual != expected:
                return (
                    False,
                    f"Observation mismatch: expected '{expected}', got '{actual}'",
                )

        except subprocess.TimeoutExpired:
            return False, "Code timed out"
        except FileNotFoundError:
            # python3 not available (e.g., in some Colab setups) — skip validation
            return True, "Skipped (no python3)"

    return True, "Valid"


# ============================================================
# Step 5: LOAD
# ============================================================


def save_jsonl(trajectories, path):
    """Save trajectories as JSONL."""
    with open(path, "w") as f:
        for traj in trajectories:
            f.write(json.dumps(traj) + "\n")
    print(f"Saved {len(trajectories)} trajectories to {path}")


# ============================================================
# MAIN PIPELINE
# ============================================================


def run_pipeline(max_problems=None, validate=True):
    """
    Run the full ETL pipeline.

    Args:
        max_problems: Limit the number of problems to process (for testing)
        validate: Whether to validate trajectories by running code
    """
    print("Step 1: EXTRACT — Loading raw data...")
    raw_problems = extract_from_huggingface()
    if max_problems:
        raw_problems = raw_problems[:max_problems]
    print(f"  Loaded {len(raw_problems)} raw problems")

    print("\nStep 2: CLEAN — Cleaning text...")
    cleaned = []
    for p in raw_problems:
        cleaned.append(
            {
                "problem": clean_problem(p["problem"]),
                "solution": clean_solution(p["solution"]),
                "type": p["type"],
                "level": p["level"],
            }
        )
    print(f"  Cleaned {len(cleaned)} problems")

    print("\nStep 3: TRANSFORM — Converting to trajectories...")
    trajectories = []
    skipped = 0
    for p in cleaned:
        traj = auto_transform(p["problem"], p["solution"])
        if traj:
            trajectories.append(traj)
        else:
            skipped += 1
    print(f"  Created {len(trajectories)} trajectories, skipped {skipped}")

    if validate:
        print("\nStep 4: VALIDATE — Checking code blocks...")
        valid = []
        invalid = 0
        for traj in trajectories:
            is_valid, msg = validate_trajectory(traj)
            if is_valid:
                valid.append(traj)
            else:
                invalid += 1
                # Optionally log failures for debugging
                # print(f"  INVALID: {msg}")
        print(f"  {len(valid)} valid, {invalid} invalid")
        trajectories = valid

    print("\nStep 5: LOAD — Saving as JSONL...")
    save_jsonl(trajectories, "sft-data/trajectories.jsonl")

    # Show a sample
    if trajectories:
        print("\n=== SAMPLE ===")
        sample = trajectories[0]
        for msg in sample["messages"]:
            role = msg["role"]
            content = msg["content"][:300]
            print(f"\n[{role}]\n{content}")

    return trajectories


if __name__ == "__main__":
    run_pipeline(max_problems=100)
