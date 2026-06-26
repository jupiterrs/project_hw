import re
import os
import sys
import subprocess
import json
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

file_names = os.listdir(DATA_DIR)


def normalizer(text: str):
    return re.sub(r"\s+", " ", text.strip())


def model_get_response(prompt: str):
    # write the code for getting the model output from the prompt
    return


data_files = []
for file_name in file_names:
    if re.search(r"""\.jsonl$""", file_name):
        data_files.append(file_name)
        print(file_name)


for filename in data_files:
    file_path = os.path.join(DATA_DIR, filename)

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            record = json.loads(line)

            messages = record["messages"]

            for msg in messages:
                if msg["role"] == "assistant":
                    # prompt = "hi there matey"
                    # model_response = model_get_response(prompt)
                    model_response = msg["content"]

                    delimiter = re.search(r"<(tool|answer)>", model_response)
                    print("NEWWWWWWW")
                    print(model_response)
                    print(delimiter)

                    if delimiter.group(0) == "<answer>":
                        ans = re.search(
                            r"<answer>\s*(.*?)\s*</answer>",
                            model_response,
                            re.DOTALL,
                        )

                        print("ASNNSDNFNLDSNF")
                        print(ans)
                        print(ans.group(0))
                        break

                    elif delimiter.group(0) == "<tool>":
                        print("CODODOOEOE")
                        code_to_run = re.search(
                            r"<tool>\s*```\s*python\s*(.*?)\s*```\s*</tool>",
                            model_response,
                            re.DOTALL,
                        )

                        print("HIHIHIH")
                        print(code_to_run.group(0))
                        print("OMGMOGMGO")
                        print(code_to_run.group(1))
                        print("NOOOOOOOOOoo")

                        with open(SANDBOX_PATH, "w") as f:
                            f.write(code_to_run.group(1))

                        result = subprocess.run(
                            [sys.executable, f"{SANDBOX_PATH}"],
                            capture_output=True,
                            text=True,
                        )

                        print(result.stdout)
