from transformers import AutoModelForCausalLM, AutoTokenizer
import re
import os
import sys
import subprocess
import json
from dotenv import load_dotenv
from typing import Optional, List, Union, Dict
### Character sets
# \d - any char that is a digit from 0 - 9
# \w - word chars (letters, numbers, underscores)
# \s - matches any whitespace (\s, \t, \n)
# . - wildcard (matches any char except newline)

# Capitalizing inverts their functions
# \D - any char not a digit

###Quantifiers (how many we want)
# * - match 0 or more times
# + - match 1 or more times
# ? - match 0 or 1 time
# {n} - match exactly n times \d{3} - match exactly three digits

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sft-data")
SANDBOX_PATH = os.path.join(DATA_DIR, "sandbox.py")
HF_TOKEN = os.environ.get("HF_TOKEN")
MODEL_ID = "meta-llama/Llama-3.2-3B"

MAX_TURNS = 10

SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."


def normalizer(text: str):
    return re.sub(r"\s+", " ", text.strip())


def model_get_response(prompt: str):
    model_tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=HF_TOKEN)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, token=HF_TOKEN)

    input = model_tokenizer(prompt, return_tensor="pt")
    output = model.generate(**input, max_new_tokens=300, do_sample=True)

    response = model_tokenizer.decode(output[0], skip_special_tokens=True)
    return response


def harness(problem_text: str) -> Dict:
    conversation = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem_text},
    ]

    problem_stats = {
        "model_answer": None,  # 1 if correct, 0 if wrong
        "num_turns": 0,  # Increments every turn
        "valid_format_turns": 0,  # Increments every time it uses tags right
        "code_attempts": 0,  # Increments every time it tries to use a tool
        "code_successes": 0,  # Increments when code runs perfectly
        "code_errors": 0,  # Increments every time code crashes
        "self_corrected": 0,  # 1 if code_errors > 0 AND task_correct == 1
        "error_observations": 0,
    }

    for turn in range(MAX_TURNS):
        model_response = model_get_response(conversation)
        problem_stats["num_turns"] += 1

        delimiter = re.search(r"<(tool|answer)>", model_response)
        # model did not follow format
        if not delimiter:
            return problem_stats

        if len(conversation) > 2 and conversation[-1]["role"] == "user":
            if "ERROR" in conversation[-1]["content"] and delimiter.group(1) == "tool":
                problem_stats["self_corrected"] += 1

        conversation.append({"role": "assistant", "content": model_response})
        problem_stats["valid_format_turns"] += 1

        if delimiter.group(1) == "answer":
            ans = re.search(r"<answer>\s*(.*?)\s*</answer>", model_response, re.DOTALL)

            if ans:
                problem_stats["model_answer"] = ans.group(1).strip()

            return problem_stats

        elif delimiter.group(1) == "tool":
            problem_stats["code_attempts"] += 1

            code_to_run = re.search(
                r"<tool>\s*```python\s*(.*?)\s*```\s*</tool>", model_response, re.DOTALL
            )

            with open(SANDBOX_PATH, "w") as f:
                f.write(code_to_run.group(1))

            result = subprocess.run(
                [sys.executable, SANDBOX_PATH], capture_output=True, text=True
            )

            if result.returncode == 0:
                problem_stats["code_successes"] += 1
                observation = f"<observation>\n{result.stdout}\n</observation>"

            else:
                problem_stats["code_errors"] += 1
                problem_stats["error_observations"] += 1
                observation = f"<observation>\n{result.stderr[:500]}\n</observation>"

            conversation.append(
                {
                    "role": "user",
                    "content": observation,
                }
            )
            continue

    return problem_stats


def load_test_data(jsonl_path: str) -> List:
    # want problem and answer values as keys and values, resp
    test_data = []

    # load the jsonl file, load the records one by one
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            record: Dict = json.loads(line)
            messages: List[Dict] = record["messages"]

            problem_message = messages[1]["content"]
            answer_message = messages[-1]["content"]

            # answer_message seems to have the <answer> delimiter, want only answer though, right?
            answer_value = re.search(
                r"<answer>\s*(.*?)\s*</answer>", answer_message, re.DOTALL
            )

            test_record: Dict[str, Union[str, int]] = {
                "problem": problem_message,
                "answer": answer_value.group(1).strip(),
            }

            test_data.append(test_record)

    return test_data


def evaluate(jsonl_path: str):
    test_data = load_test_data(jsonl_path)
    total_problems = len(test_data)
    all_stats = []
    total_correct_tasks = 0

    print(f"Running evaluation on {total_problems} problems")

    for record in test_data:
        stats = harness(record["problem"])

        if stats["model_answer"] == record["answer"]:
            total_correct_tasks += 1

        all_stats.append(stats)

    total_turns = sum(s["num_turns"] for s in all_stats)
    total_valid_formats = sum(s["valid_format_turns"] for s in all_stats)
    total_code_attempts = sum(s["code_attempts"] for s in all_stats)
    total_code_successes = sum(s["code_successes"] for s in all_stats)
    total_code_errors = sum(s["code_errors"] for s in all_stats)
    total_self_corrections = sum(s["self_corrected"] for s in all_stats)
    problems_with_code_errors = sum(s["error_observations"] for s in all_stats)

    accuracy = (total_correct_tasks / total_problems) * 100 if total_problems else 0
    format_rate = (total_valid_formats / total_turns) * 100 if total_turns else 0
    code_success_rate = (
        (total_code_successes / total_code_attempts) * 100 if total_code_attempts else 0
    )
    self_correction_rate = (
        (total_self_corrections / problems_with_code_errors) * 100
        if problems_with_code_errors
        else 0
    )
    code_error_rate = (
        (total_code_errors / total_code_attempts) * 100 if total_code_attempts else 0
    )
    avg_turns = total_turns / total_problems if total_problems else 0

    print("\n================ EVALUATION SUMMARY ================")
    print(f"Task Accuracy          : {accuracy:.2f}%")
    print(f"Format Compliance Rate : {format_rate:.2f}%")
    print(f"Code Success Rate      : {code_success_rate:.2f}%")
    print(f"Code Error Rate      : {code_error_rate:.2f}%")
    print(f"Self-Correction Rate   : {self_correction_rate:.2f}%")
    print(f"Average Turns/Problem  : {avg_turns:.2f}")
    print("====================================================")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(DATA_DIR, "aime_2005_trajectories_multiturn.jsonl"),
    )
    args = parser.parse_args()
    evaluate(args.data)
