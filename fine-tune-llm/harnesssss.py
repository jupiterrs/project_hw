from transformers import AutoModelForCausalLM, AutoTokenizer
import re
import os
import sys
import subprocess
import json
from dotenv import load_dotenv
from typing import List, Dict

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sft-data")
SANDBOX_PATH = os.path.join(DATA_DIR, "sandbox.py")
os.makedirs(DATA_DIR, exist_ok=True)

HF_TOKEN = os.environ.get("HF_TOKEN")

MODEL_ID = "meta-llama/Llama-3.2-3B"

MAX_TURNS = 10
SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. Each tool execution runs in a completely fresh, isolated Python environment. You must include all necessary imports and print your final variables in every block. If you make an error, correct yourself. Wrap your tool code inside <tool>```python ... ```</tool> and your final answer in <answer>...</answer>."


print("Loading tokenizer and model...")
model_tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=HF_TOKEN)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, token=HF_TOKEN, device_map="auto"
)


def normalize_answer(ans: str) -> str:
    if not ans:
        return ""
    ans = ans.strip(" \n\"'`.")
    try:
        f_ans = float(ans)
        if f_ans.is_integer():
            return str(int(f_ans))
        return str(f_ans)
    except ValueError:
        return ans


def format_conv(conversation: List[Dict]) -> str:
    parts = ["<|begin_of_text|>"]

    for msg in conversation:
        parts.append(
            f"<|start_header_id|>{msg['role']}<|end_header_id|>\n\n{msg['content']}<|eot_id|>"
        )
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


def model_get_response(conversation: List[Dict]):
    prompt = format_conv(conversation)

    inputs = model_tokenizer(prompt, return_tensors="pt").to("cuda")
    input_len = inputs["input_ids"].shape[1]

    pad_id = (
        model_tokenizer.eos_token_id
        if model_tokenizer.pad_token_id is None
        else model_tokenizer.pad_token_id
    )

    output = model.generate(
        **inputs,
        max_new_tokens=300,
        do_sample=True,
        temperature=0.6,
        repetition_penalty=1.2,
        pad_token_id=pad_id,
    )

    # Decode without skipping special tokens so we can detect end-of-turn
    raw_response = model_tokenizer.decode(
        output[0][input_len:], skip_special_tokens=False
    )
    # Truncate at the first end-of-turn or start-of-turn marker
    stop_match = re.search(r"<\|eot_id\|>|<\|start_header_id\|>", raw_response)
    if stop_match:
        raw_response = raw_response[: stop_match.start()]
    # Now strip any remaining special tokens for clean output
    response = model_tokenizer.decode(
        model_tokenizer.encode(raw_response, add_special_tokens=False),
        skip_special_tokens=True,
    )

    return response.strip()


def harness(problem_text: str) -> tuple[Dict, List]:
    conversation = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem_text},
    ]

    problem_stats = {
        "model_answer": None,
        "answer_source": None,  # "tagged" or "fallback"
        "num_turns": 0,
        "valid_format_turns": 0,
        "code_attempts": 0,
        "code_successes": 0,
        "code_errors": 0,
        "self_corrected": 0,
        "error_observations": 0,
    }

    turns_log = []

    for turn in range(MAX_TURNS):
        prompt_text = format_conv(conversation)
        model_response = model_get_response(conversation)
        problem_stats["num_turns"] += 1

        turns_log.append(
            {
                "turn": turn + 1,
                "prompt": prompt_text,
                "response": model_response,
            }
        )

        delimiter = re.search(r"<(tool|answer)>", model_response)
        if not delimiter:
            numbers = re.findall(r"(?<!\d)-?\d{1,6}(?!\d)", model_response)
            if numbers:
                problem_stats["model_answer"] = numbers[-1]
                problem_stats["answer_source"] = "fallback"
            conversation.append({"role": "assistant", "content": model_response})
            conversation.append(
                {
                    "role": "user",
                    "content": "Please wrap your final answer in <answer>...</answer> tags, or use <tool>```python ... ```</tool> to run code.",
                }
            )
            if turn == MAX_TURNS - 1:
                return problem_stats, turns_log
            continue

        if len(conversation) > 2 and conversation[-1]["role"] == "user":
            if "ERROR" in conversation[-1]["content"] and delimiter.group(1) == "tool":
                problem_stats["self_corrected"] += 1

        conversation.append({"role": "assistant", "content": model_response})
        problem_stats["valid_format_turns"] += 1

        if delimiter.group(1) == "answer":
            ans = re.search(r"<answer>\s*(.*?)\s*</answer>", model_response, re.DOTALL)
            if ans:
                problem_stats["model_answer"] = ans.group(1).strip()
                problem_stats["answer_source"] = "tagged"
            else:
                problem_stats["model_answer"] = model_response.split("<answer>")[
                    -1
                ].strip()
                problem_stats["answer_source"] = "fallback"
            return problem_stats, turns_log

        elif delimiter.group(1) == "tool":
            problem_stats["code_attempts"] += 1

            code_to_run = re.search(
                r"<tool>\s*```python\s*(.*?)\s*```\s*</tool>", model_response, re.DOTALL
            )
            if not code_to_run:
                code_to_run = re.search(
                    r"<tool>\s*(.*?)\s*</tool>", model_response, re.DOTALL
                )

            if not code_to_run:
                problem_stats["code_errors"] += 1
                observation = "<observation>\nERROR: Invalid python block layout inside tool tags.\n</observation>"
            else:
                with open(SANDBOX_PATH, "w") as f:
                    f.write(code_to_run.group(1))

                try:
                    result = subprocess.run(
                        [sys.executable, SANDBOX_PATH],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )

                    if result.returncode == 0:
                        problem_stats["code_successes"] += 1
                        observation = (
                            f"<observation>\n{result.stdout[:2000]}\n</observation>"
                        )
                    else:
                        problem_stats["code_errors"] += 1
                        problem_stats["error_observations"] += 1
                        observation = f"<observation>\nERROR:\n{result.stderr[:500]}\n</observation>"

                except subprocess.TimeoutExpired:
                    problem_stats["code_errors"] += 1
                    problem_stats["error_observations"] += 1
                    observation = "<observation>\nERROR: Execution timed out (infinite loop detected).\n</observation>"

            conversation.append({"role": "user", "content": observation})
            continue

    return problem_stats, turns_log


def load_test_data(jsonl_path: str) -> List:
    test_data = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record: Dict = json.loads(line)
            messages: List[Dict] = record["messages"]

            problem_message = messages[1]["content"]
            answer_message = messages[-1]["content"]

            answer_value = re.search(
                r"<answer>\s*(.*?)\s*</answer>", answer_message, re.DOTALL
            )
            extracted_ans = (
                answer_value.group(1).strip()
                if answer_value
                else answer_message.strip()
            )

            test_record = {
                "problem": problem_message,
                "answer": extracted_ans,
            }
            test_data.append(test_record)
    return test_data


def evaluate(jsonl_path: str, output_path: str = None):
    test_data = load_test_data(jsonl_path)
    total_problems = len(test_data)
    all_stats = []
    all_trajectories = []
    total_correct_tasks = 0

    print(f"Running evaluation on {total_problems} problems")

    for idx, record in enumerate(test_data):
        print(f"Evaluating Problem {idx + 1}/{total_problems}...")
        stats, turns_log = harness(record["problem"])

        if normalize_answer(stats["model_answer"]) == normalize_answer(
            record["answer"]
        ):
            total_correct_tasks += 1

        all_stats.append(stats)

        all_trajectories.append(
            {
                "problem": record["problem"],
                "true_answer": record["answer"],
                "stats": stats,
                "turns": turns_log,
            }
        )

    if output_path is None:
        output_path = os.path.join(BASE_DIR, "eval_trajectories.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for traj in all_trajectories:
            f.write(json.dumps(traj) + "\n")
    print(f"Saved trajectories to {output_path}")

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
    code_error_rate = (
        (total_code_errors / total_code_attempts) * 100 if total_code_attempts else 0
    )
    self_correction_rate = (
        (total_self_corrections / problems_with_code_errors) * 100
        if problems_with_code_errors
        else 0
    )
    avg_turns = total_turns / total_problems if total_problems else 0

    tagged_answers = sum(1 for s in all_stats if s["answer_source"] == "tagged")
    fallback_answers = sum(1 for s in all_stats if s["answer_source"] == "fallback")
    no_answer = sum(1 for s in all_stats if s["model_answer"] is None)

    print("\n================ EVALUATION SUMMARY ================")
    print(f"Task Accuracy          : {accuracy:.2f}%")
    print(f"Tagged Answers         : {tagged_answers}")
    print(f"Fallback Answers       : {fallback_answers}")
    print(f"No Answer              : {no_answer}")
    print(f"Format Compliance Rate : {format_rate:.2f}%")
    print(f"Code Success Rate      : {code_success_rate:.2f}%")
    print(f"Code Error Rate        : {code_error_rate:.2f}%")
    print(f"Self-Correction Rate   : {self_correction_rate:.2f}%")
    print(f"Average Turns/Problem  : {avg_turns:.2f}")
    print("====================================================")

    # Save evaluation report alongside trajectories
    summary = {
        "model_id": MODEL_ID,
        "dataset": jsonl_path,
        "total_problems": total_problems,
        "metrics": {
            "task_accuracy": round(accuracy, 2),
            "format_compliance_rate": round(format_rate, 2),
            "code_success_rate": round(code_success_rate, 2),
            "code_error_rate": round(code_error_rate, 2),
            "self_correction_rate": round(self_correction_rate, 2),
            "avg_turns_per_problem": round(avg_turns, 2),
        },
        "answer_breakdown": {
            "tagged": tagged_answers,
            "tagged_explanation": "model used <answer>...</answer> tags correctly",
            "fallback": fallback_answers,
            "fallback_explanation": "no <answer> tag found, answer extracted from last number in response",
            "no_answer": no_answer,
            "correct": total_correct_tasks,
        },
        "per_problem": [
            {
                "problem_idx": i + 1,
                "true_answer": all_trajectories[i]["true_answer"],
                "model_answer": s["model_answer"],
                "answer_source": s["answer_source"],
                "correct": normalize_answer(s["model_answer"])
                == normalize_answer(all_trajectories[i]["true_answer"]),
                "num_turns": s["num_turns"],
                "code_attempts": s["code_attempts"],
            }
            for i, s in enumerate(all_stats)
        ],
    }
    summary_path = (
        output_path.replace(".jsonl", "_summary.json")
        if output_path
        else os.path.join(BASE_DIR, "eval_summary.json")
    )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved summary to {summary_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=str,
        default=os.path.join(DATA_DIR, "aime_test.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save trajectory JSONL (default: eval_trajectories.jsonl)",
    )
    args = parser.parse_args()
    evaluate(args.data, args.output)
