import re
import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "sft-data"
SANDBOX_PATH = DATA_DIR / "sandbox.py"

SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."

MAX_TURNS = 10
TIMEOUT_SECONDS = 10


def extract_code(model_output: str) -> Optional[str]:
    """Extract Python code from a <tool> block in model output."""
    match = re.search(r"<tool>\s*```\s*python(.*?)```\s*</tool>", model_output, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_answer(model_output: str) -> Optional[str]:
    """Extract answer from an <answer> block in model output."""
    match = re.search(r"<answer>\s*(.*?)\s*</answer>", model_output, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def run_code(code: str) -> tuple[str, str, bool]:
    """Run Python code in sandbox. Returns (stdout, stderr, success)."""
    with open(SANDBOX_PATH, "w") as f:
        f.write(code)

    try:
        result = subprocess.run(
            [sys.executable, SANDBOX_PATH],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode == 0
    except subprocess.TimeoutExpired:
        return "", f"TIMEOUT: code exceeded {TIMEOUT_SECONDS}s", False
    finally:
        if SANDBOX_PATH.exists():
            SANDBOX_PATH.unlink()


def generate(model, tokenizer, messages: list[dict]) -> str:
    """Generate a response from the model given conversation history."""
    input_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

    outputs = model.generate(
        **inputs,
        max_new_tokens=2048,
        do_sample=False,
        temperature=1.0,
        pad_token_id=tokenizer.eos_token_id,
    )

    # Decode only the new tokens (skip the prompt)
    new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True)


def harness(model, tokenizer, problem_text: str, verbose: bool = False) -> dict:
    """Run the agent loop: model thinks -> harness runs code -> loop until <answer>.

    Returns dict with:
        - answer: the model's final answer (or None)
        - turns: number of conversation turns
        - messages: full conversation history
        - error: any error that stopped the loop
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem_text},
    ]

    answer = None
    error = None

    for turn in range(MAX_TURNS):
        if verbose:
            print(f"\n--- Turn {turn + 1} ---")

        # Model generates a response
        try:
            model_output = generate(model, tokenizer, messages)
        except Exception as e:
            error = f"Generation error: {e}"
            break

        if verbose:
            print(f"Model: {model_output[:200]}...")

        messages.append({"role": "assistant", "content": model_output})

        # Check if model gave an answer
        extracted_answer = extract_answer(model_output)
        if extracted_answer:
            answer = extracted_answer
            if verbose:
                print(f"Answer: {answer}")
            break

        # Check if model wrote code
        code = extract_code(model_output)
        if code:
            stdout, stderr, success = run_code(code)

            if success and stdout:
                observation = f"<observation>\n{stdout}\n</observation>"
            else:
                observation = f"<observation>\nERROR: {stderr[:500]}\n</observation>"

            if verbose:
                print(f"Observation: {observation[:150]}...")

            messages.append({"role": "user", "content": observation})
            continue

        # Model wrote text with no code and no answer — stop
        error = "Model produced no <tool> or <answer> block"
        break
    else:
        error = f"Reached max turns ({MAX_TURNS})"

    return {
        "answer": answer,
        "turns": len([m for m in messages if m["role"] == "assistant"]),
        "messages": messages,
        "error": error,
    }


def evaluate(model, tokenizer, test_data: list[dict], verbose: bool = False) -> dict:
    """Evaluate the model on a list of test problems.

    Each test_data entry should have:
        - "problem": the problem text
        - "answer": the correct answer string

    Returns dict with:
        - correct: number of correct answers
        - total: total number of problems
        - accuracy: correct / total
        - results: per-problem details
    """
    results = []
    correct = 0

    for i, entry in enumerate(test_data):
        problem = entry["problem"]
        expected = entry["answer"]

        if verbose:
            print(f"\n{'='*60}")
            print(f"Problem {i+1}: {problem[:80]}...")
            print(f"Expected answer: {expected}")

        result = harness(model, tokenizer, problem, verbose=verbose)
        result["expected"] = expected
        result["problem_num"] = i + 1

        if result["answer"] and result["answer"].strip() == expected.strip():
            correct += 1
            result["correct"] = True
            if verbose:
                print(f"CORRECT!")
        else:
            result["correct"] = False
            if verbose:
                print(f"WRONG: got '{result['answer']}', expected '{expected}'")

        results.append(result)

    total = len(test_data)
    accuracy = correct / total if total > 0 else 0

    return {
        "correct": correct,
        "total": total,
        "accuracy": accuracy,
        "results": results,
    }


def load_test_data(jsonl_path: Path) -> list[dict]:
    """Load test problems from a multi-turn JSONL file.

    Extracts the user's problem text and the correct answer.
    """
    test_data = []
    with open(jsonl_path, "r") as f:
        for line in f:
            entry = json.loads(line)
            messages = entry["messages"]

            # Find the first user message (the problem)
            problem = None
            for msg in messages:
                if msg["role"] == "user" and "<observation>" not in msg["content"]:
                    problem = msg["content"]
                    break

            # Find the answer from the last assistant message
            answer = None
            for msg in reversed(messages):
                if msg["role"] == "assistant":
                    extracted = extract_answer(msg["content"])
                    if extracted:
                        answer = extracted
                        break

            if problem and answer:
                test_data.append({"problem": problem, "answer": answer})

    return test_data


if __name__ == "__main__":
    # Quick test: load test data and print
    multiturn_jsonl = DATA_DIR / "aime_2005_trajectories_multiturn.jsonl"
    if multiturn_jsonl.exists():
        test_data = load_test_data(multiturn_jsonl)
        print(f"Loaded {len(test_data)} test problems")
        for td in test_data[:3]:
            print(f"  Problem: {td['problem'][:60]}... Answer: {td['answer']}")
    else:
        print(f"No test data found at {multiturn_jsonl}")
        print("Run restructure_trajectories.py first")