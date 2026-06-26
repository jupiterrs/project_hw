import re
import os
import sys
import json
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "sft-data"
EXTRACTED_DIR = BASE_DIR / "aime_pdfs" / "extracted"
SANDBOX_PATH = DATA_DIR / "sandbox.py"

MODEL_ID = "Qwen/Qwen2.5-72B-Instruct"

SYSTEM_PROMPT = """You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself.

When you write code, wrap it in <tool> blocks like this:
<tool>
```python
# your code here
```
</tool>

After each code block, write the expected output in an <observation> block:
<observation>
<code output here>
</observation>

When you have the final answer, write it in an <answer> block:
<answer>
<your answer as a 3-digit integer>
</answer>

Guidelines:
- Start by thinking through the problem in natural language
- Write Python code to compute or verify key steps
- Include brute force cross-checks when possible
- If your initial approach has an error, show the correction process
- End with the final answer in a <answer> block"""


def normalizer(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def extract_problems(problems_md: str) -> list[dict]:
    """Extract individual problems from AIME problems markdown."""
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
            text = re.split(r"\nYour Exam|CONTACT US|PUBLICATIONS|The\n", text)[0]
            problems.append({"number": num, "text": text.strip()})
    return problems


def extract_solutions(solutions_md: str) -> list[dict]:
    """Extract individual solutions from AIME solutions markdown."""
    pattern = re.compile(r"(?:#\s*)?(\d+)\.\s*\(Answer:\s*(\d+)\)", re.MULTILINE)
    solutions = []
    matches = list(pattern.finditer(solutions_md))
    for idx, match in enumerate(matches):
        num = int(match.group(1))
        answer = match.group(2)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(solutions_md)
        solution_text = solutions_md[start:end].strip()
        solutions.append({"number": num, "answer": answer, "text": solution_text})
    return solutions


def run_code_and_get_output(code: str) -> tuple[str, str, bool]:
    """Run Python code in sandbox and return (stdout, stderr, success)."""
    with open(SANDBOX_PATH, "w") as f:
        f.write(code)

    try:
        result = subprocess.run(
            [sys.executable, SANDBOX_PATH],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT: code took longer than 10 seconds", False


def validate_and_fix_trajectory(content: str) -> tuple[str, dict]:
    """Validate a trajectory by running its code blocks and fixing observations."""
    code_blocks = re.findall(
        r"<tool>\s*```\s*python(.*?)\s*```\s*</tool>", content, re.DOTALL
    )
    obs_blocks = re.findall(
        r"<observation>\s*(.*?)\s*</observation>", content, re.DOTALL
    )

    stats = {"total_blocks": len(code_blocks), "matches": 0, "fixes": 0, "crashes": 0}

    if len(code_blocks) != len(obs_blocks):
        stats["block_count_mismatch"] = True
        return content, stats

    for i, code in enumerate(code_blocks):
        stdout, stderr, success = run_code_and_get_output(code)

        if not success:
            stats["crashes"] += 1
            print(f"    Block {i}: CRASH - {stderr[:100]}")
            continue

        if normalizer(stdout) == normalizer(obs_blocks[i]):
            stats["matches"] += 1
        else:
            stats["fixes"] += 1
            old_obs = obs_blocks[i]
            content = content.replace(
                f"<observation>{old_obs}</observation>",
                f"<observation>\n{stdout}\n</observation>",
                1,
            )

    if SANDBOX_PATH.exists():
        SANDBOX_PATH.unlink()

    return content, stats


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


def format_trajectory_jsonl(problem_text: str, solution_text: str, answer: str, trajectory: str) -> dict:
    """Format a validated trajectory into multi-turn JSONL format for SFTTrainer."""
    system_prompt = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."
    return split_trajectory_to_multiturn(trajectory, system_prompt, problem_text)


def generate_trajectory(client: InferenceClient, problem_text: str, solution_text: str, max_retries: int = 3) -> str:
    """Call HF Inference API to generate an agentic trajectory."""
    user_prompt = f"""Solve this AIME problem step by step. Use Python code to verify your work.

Problem:
{problem_text}

Reference solution (use this to guide your reasoning, but show the full thinking process):
{solution_text}

Remember to:
1. Think through the problem first
2. Write Python code in <tool> blocks to verify computations
3. Write the output in <observation> blocks
4. If you make an error, show the correction
5. End with the final answer in an <answer> block"""

    for attempt in range(max_retries):
        try:
            response = client.chat_completion(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"    Attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                print(f"    Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def process_aime_year(
    client: InferenceClient,
    problems_path: Path,
    solutions_path: Path,
    output_jsonl: Path,
    max_problems: int = 15,
):
    """Process one AIME year: extract problems, generate trajectories, validate, save."""
    print(f"\n{'='*60}")
    print(f"Processing: {problems_path.stem}")
    print(f"{'='*60}")

    problems_md = problems_path.read_text()
    solutions_md = solutions_path.read_text()

    problems = extract_problems(problems_md)
    solutions = extract_solutions(solutions_md)

    if not problems:
        print("  No problems found!")
        return

    if not solutions:
        print("  No solutions found!")
        return

    solution_lookup = {s["number"]: s for s in solutions}

    existing = set()
    if output_jsonl.exists():
        with open(output_jsonl, "r") as f:
            for line in f:
                data = json.loads(line)
                existing.add(data["messages"][1]["content"][:50])

    for prob in problems[:max_problems]:
        num = prob["number"]
        sol = solution_lookup.get(num)

        if not sol:
            print(f"  Problem {num}: No solution found, skipping")
            continue

        if prob["text"][:50] in existing:
            print(f"  Problem {num}: Already exists, skipping")
            continue

        print(f"\n  Problem {num}: Generating trajectory...")

        try:
            trajectory = generate_trajectory(client, prob["text"], sol["text"])
        except Exception as e:
            print(f"    API error: {e}")
            time.sleep(10)
            continue

        print(f"    Validating...")
        fixed_trajectory, stats = validate_and_fix_trajectory(trajectory)
        print(f"    Blocks: {stats['total_blocks']}, Matches: {stats['matches']}, Fixes: {stats['fixes']}, Crashes: {stats['crashes']}")

        answer_match = re.search(r"<answer>\s*(\d+)\s*</answer>", fixed_trajectory)
        if answer_match:
            traj_answer = answer_match.group(1)
            if traj_answer == sol["answer"]:
                print(f"    Answer: {traj_answer} CORRECT")
            else:
                print(f"    Answer: {traj_answer} WRONG (expected {sol['answer']})")
        else:
            print(f"    WARNING: No <answer> block found")

        entry = format_trajectory_jsonl(
            prob["text"], sol["text"], sol["answer"], fixed_trajectory
        )

        with open(output_jsonl, "a") as f:
            f.write(json.dumps(entry) + "\n")

        time.sleep(3)


def main():
    api_key = os.environ.get("HF_TOKEN", "")

    if not api_key:
        print("ERROR: Set HF_TOKEN in .env")
        sys.exit(1)

    client = InferenceClient(api_key=api_key)

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

    if not paired:
        print("No paired problem/solution files found in extracted/")
        sys.exit(1)

    print(f"Found {len(paired)} paired exams to process ({len(paired) * 15} problems total)")
    for key in paired:
        print(f"  {key}")

    for key in paired:
        output_name = key.lower().replace("aimei_", "aime_i_").replace("aimeii_", "aime_ii_")
        output_jsonl = DATA_DIR / f"{output_name}_trajectories.jsonl"

        process_aime_year(
            client,
            problem_files[key],
            solution_files[key],
            output_jsonl,
        )

    print(f"\n{'='*60}")
    print("All done!")


if __name__ == "__main__":
    main()