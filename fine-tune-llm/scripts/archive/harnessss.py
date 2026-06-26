import re
import os
import sys
import subprocess
import json
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sft-data")
SANDBOX_PATH = os.path.join(DATA_DIR, "sandbox.py")

MAX_TURNS = 4

SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."


def normalizer(text: str):
    return re.sub(r"\s+", " ", text.strip())


def model_get_response(prompt: str):
    # write the code for getting the model output from the prompt
    return "hi there, my name is rolanda"
    return


def harness(problem_text: str) -> Optional[str]:
    conversation = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": problem_text},
    ]

    problem_stats = {
        "model_answer": None,        # 1 if correct, 0 if wrong
        "total_turns": 0,         # Increments every turn
        "valid_format_turns": 0,  # Increments every time it uses tags right
        "code_attempts": 0,       # Increments every time it tries to use a tool
        "code_successes": 0,      # Increments when code runs perfectly
        "code_errors": 0,         # Increments every time code crashes
        "self_corrected": 0       # 1 if code_errors > 0 AND task_correct == 1
    }

    for turn in range(MAX_TURNS):
        model_response = model_get_response(conversation)

        delimiter = re.search(r"<(tool|answer)>", model_response)

        # model did not follow format
        if not delimiter:
            return None

        conversation.append({"role": "assistant", "content": model_response})

        if delimiter.group(1) == "answer":
            ans = re.search(r"<answer>\s*(.*?)\s*</answer>", model_response, re.DOTALL)

            return ans.group(1)

        elif delimiter.group(1) == "tool":
            code_to_run = re.search(
                r"<tool>\s*```python\s*(.*?)\s*```\s*</tool>", model_response, re.DOTALL
            )

            with open(SANDBOX_PATH, "w") as f:
                f.write(code_to_run.group(1))

            result = subprocess.run(
                [sys.executable, SANDBOX_PATH], capture_output=True, text=True
            )

            conversation.append(
                {
                    "role": "user",
                    "content": f"<observation>\n{result.stdout}\n</observation>",
                }
            )
            continue

        return None

def load_test_data(jsonl_path: str) -> List:
    # want problem and answer values as keys and values, resp
    test_data = []

    # load the jsonl file, load its content one by one
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            record: Dict = json.loads(line)
            messages: List[Dict] = record["messages"]

            problem_message = messages[1]["content"]
            answer_message = messages[-1]["content"]

            # answer_message seems to have the <answer> delimiter, want only answer though, right?

            answer_value = re.search(r'<answer>\s*(.*?)\s*</answer>', answer_message, re.DOTALL)

            test_record: Dict[str, Union[str, int]] = {"problem": problem_message, "answer": answer_value.group(1).strip()}

            test_data.append(test_record)

    return test_data

def evaluate(test_data: List(Dict)):
    for record in test_dat
    
