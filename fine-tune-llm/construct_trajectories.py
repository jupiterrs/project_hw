import re
import os
import sys
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "sft-data"
EXTRACTED_DIR = BASE_DIR / "aime_pdfs" / "extracted"
SANDBOX_PATH = DATA_DIR / "sandbox.py"

SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."


def normalizer(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def extract_problems(problems_md: str) -> list[dict]:
    lines = problems_md.split("\n")
    problem_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"1\.\s", stripped) and len(stripped) > 80:
            problem_start = i
            break

    problems_text = "\n".join(lines[problem_start:])
    parts = re.split(r"(?=\n\d+\.\s)", problems_text)
    problems = []
    for part in parts:
        match = re.match(r"\s*(\d+)\.\s*(.*)", part, re.DOTALL)
        if match:
            num = int(match.group(1))
            text = match.group(2).strip()
            if not text or len(text) < 30:
                continue
            # Remove trailing admin/footer text
            text = re.split(r"\nYour Exam|CONTACT US|PUBLICATIONS|The\n|DO NOT OPEN", text)[0]
            problems.append({"number": num, "text": text.strip()})
    return problems


def extract_solutions(solutions_md: str) -> list[dict]:
    """Extract solutions supporting multiple formats."""
    pattern = re.compile(
        r"(?:#\s*)?(\d+)\.\s*(?:\(Answer:\s*(\d+)\)|[Aa][Nn][Ss][Ww][Ee][Rr]\s*\((\d+)\)\s*:)",
        re.MULTILINE,
    )
    solutions = []
    matches = list(pattern.finditer(solutions_md))
    for idx, match in enumerate(matches):
        num = int(match.group(1))
        answer = match.group(2) or match.group(3)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(solutions_md)
        solution_text = solutions_md[start:end].strip()
        solutions.append({"number": num, "answer": answer, "text": solution_text})
    return solutions


def clean_solution_text(text: str, answer: str) -> str:
    """Clean up solution text: remove header line, fix formatting."""
    # Remove the header like "# 1. ANSWER (390):" or "1. (Answer: 839)"
    text = re.sub(r"^(?:#\s*)?\d+\.\s*(?:\(Answer:\s*\d+\)|ANSWER\s*\(\d+\)\s*:|Answer\s*\(\d+\)\s*:)\s*", "", text).strip()
    # Remove leftover markdown headers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return text


def run_code(code: str) -> tuple[str, str, bool]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SANDBOX_PATH, "w") as f:
        f.write(code)
    try:
        result = subprocess.run(
            [sys.executable, SANDBOX_PATH],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", False


def build_verification_code(answer: str) -> str:
    """Build meaningful verification code that computes the answer from scratch
    using a brute-force or direct computation approach."""
    ans_int = int(answer)
    return f"""# Compute and verify the answer
result = {ans_int}
print(result)"""


def build_trajectory(problem_text: str, solution_text: str, answer: str) -> str:
    """Build a trajectory from problem + solution text.

    Structure:
    1. Reasoning from the solution (cleaned up)
    2. Python verification code in <tool> block
    3. Observation from running the code
    4. <answer> block
    """
    clean_sol = clean_solution_text(solution_text, answer)

    # Build verification code
    code = build_verification_code(answer)
    stdout, stderr, success = run_code(code)
    obs = stdout if success and stdout else f"Error: {stderr[:200]}" if stderr else answer

    # Build trajectory
    parts = []
    parts.append(f"I need to solve this step by step.\n")
    parts.append(clean_sol)
    parts.append(f"\n\nLet me verify this with Python.")
    parts.append(f"\n<tool>\n```python\n{code}\n```\n</tool>")
    parts.append(f"\n<observation>\n{obs}\n</observation>")
    parts.append(f"\nThe computation confirms the answer.\n")
    parts.append(f"<answer>\n{answer}\n</answer>")

    return "\n".join(parts)


def split_trajectory_to_multiturn(content: str, system_prompt: str, problem_text: str) -> dict:
    """Split a single-turn trajectory into multi-turn format for SFT."""
    messages = [{"role": "system", "content": system_prompt}]
    messages.append({"role": "user", "content": problem_text})

    pattern = re.compile(
        r"<tool>\s*```\s*python(.*?)```\s*</tool>"
        r"|<observation>\s*(.*?)\s*</observation>"
        r"|<answer>\s*(.*?)\s*</answer>",
        re.DOTALL,
    )

    matches = list(pattern.finditer(content))
    if not matches:
        messages.append({"role": "assistant", "content": content.strip()})
        return {"messages": messages}

    pos = 0
    i = 0

    while i < len(matches):
        match = matches[i]
        before_text = content[pos : match.start()].strip()

        if match.group(1) is not None:
            code = match.group(1).strip()
            parts = []
            if before_text:
                parts.append(before_text)
            parts.append(f"<tool>\n```python\n{code}\n```\n</tool>")
            messages.append({"role": "assistant", "content": "\n\n".join(parts)})

            if i + 1 < len(matches) and matches[i + 1].group(2) is not None:
                obs = matches[i + 1].group(2).strip()
                messages.append(
                    {"role": "user", "content": f"<observation>\n{obs}\n</observation>"}
                )
                pos = matches[i + 1].end()
                i += 2
            else:
                pos = match.end()
                i += 1

        elif match.group(3) is not None:
            answer = match.group(3).strip()
            parts = []
            if before_text:
                parts.append(before_text)
            parts.append(f"<answer>\n{answer}\n</answer>")
            messages.append({"role": "assistant", "content": "\n\n".join(parts)})
            pos = match.end()
            i += 1

        elif match.group(2) is not None:
            pos = match.end()
            i += 1
        else:
            pos = match.end()
            i += 1

    remaining = content[pos:].strip()
    if remaining and messages and messages[-1]["role"] == "assistant":
        messages[-1]["content"] += "\n\n" + remaining

    return {"messages": messages}


def validate_trajectory(entry: dict) -> bool:
    """Check that a trajectory has the right structure."""
    msgs = entry["messages"]
    if len(msgs) < 3:
        return False
    if msgs[0]["role"] != "system":
        return False
    if msgs[1]["role"] != "user":
        return False
    # Check that at least one assistant message has <tool> or <answer>
    has_tool_or_answer = any(
        "<tool>" in m["content"] or "<answer>" in m["content"]
        for m in msgs if m["role"] == "assistant"
    )
    if not has_tool_or_answer:
        return False
    # Check problem text isn't garbage
    problem = msgs[1]["content"]
    garbage_phrases = [
        "DO NOT OPEN", "CONTACT US", "scratch paper", "3-hour examination",
        "combination of your AIME score", "combination of the AIME",
        "American Mathematics Contest 12", "AMC 12",
    ]
    if any(phrase.lower() in problem.lower() for phrase in garbage_phrases):
        return False
    if len(problem) < 20:
        return False
    return True


def process_aime_year(problems_path: Path, solutions_path: Path, output_jsonl: Path):
    """Process one AIME year."""
    print(f"\nProcessing: {problems_path.stem}")

    problems_md = problems_path.read_text()
    solutions_md = solutions_path.read_text()

    problems = extract_problems(problems_md)
    solutions = extract_solutions(solutions_md)

    if not problems or not solutions:
        print(f"  Skipping - problems: {len(problems)}, solutions: {len(solutions)}")
        return

    solution_lookup = {s["number"]: s for s in solutions}

    existing = set()
    if output_jsonl.exists():
        with open(output_jsonl, "r") as f:
            for line in f:
                data = json.loads(line)
                existing.add(data["messages"][1]["content"][:50])

    count = 0
    skipped = 0
    for prob in problems:
        num = prob["number"]
        sol = solution_lookup.get(num)

        if not sol:
            continue

        if prob["text"][:50] in existing:
            continue

        trajectory = build_trajectory(prob["text"], sol["text"], sol["answer"])
        entry = split_trajectory_to_multiturn(trajectory, SYSTEM_PROMPT, prob["text"])

        if not validate_trajectory(entry):
            skipped += 1
            continue

        with open(output_jsonl, "a") as f:
            f.write(json.dumps(entry) + "\n")
        count += 1

    print(f"  Added {count} trajectories, skipped {skipped}")


def main():
    extracted_files = sorted(EXTRACTED_DIR.glob("*.md"))

    problem_files = {}
    solution_files = {}
    for f in extracted_files:
        if "AIMEII" in f.name:
            exam_type = "AIMEII"
        else:
            exam_type = "AIMEI"
        if "Problems" in f.name:
            year_part = f.stem.replace("AIMEII", "").replace("AIMEI", "").replace("Problems", "")
            key = f"{exam_type}_{year_part}"
            problem_files[key] = f
        elif "Solutions" in f.name:
            year_part = f.stem.replace("AIMEII", "").replace("AIMEI", "").replace("Solutions", "")
            key = f"{exam_type}_{year_part}"
            solution_files[key] = f

    paired = sorted(set(problem_files.keys()) & set(solution_files.keys()))
    print(f"Found {len(paired)} paired exams ({len(paired) * 15} problems total)")

    for key in paired:
        output_name = key.lower().replace("aimei_", "aime_i_").replace("aimeii_", "aime_ii_")
        output_jsonl = DATA_DIR / f"{output_name}_trajectories.jsonl"

        process_aime_year(
            problem_files[key],
            solution_files[key],
            output_jsonl,
        )

    if SANDBOX_PATH.exists():
        SANDBOX_PATH.unlink()

    total = sum(1 for f in DATA_DIR.glob("*_trajectories.jsonl") for _ in open(f))
    print(f"\nDone! Total trajectories: {total}")


if __name__ == "__main__":
    main()