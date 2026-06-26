from transformers import AutoTokenizer
import os
from dotenv import load_dotenv
import json
import harnesssss

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "sft-data")
SFT_DATA = os.path.join(DATA_DIR, "trajectories_example.jsonl")
HF_TOKEN = os.environ.get("HF_TOKEN")

# loads reads a json object from string, load reads a json object from function object
with open(SFT_DATA, "r") as f:
    for line in f:
        data = json.loads(line)
        messages = data["messages"]

        tokenizer = AutoTokenizer.from_pretrained(
            "meta-llama/Llama-3.2-1B-Instruct", token=HF_TOKEN
        )
        text = tokenizer.apply_chat_template(messages, tokenize=False)

        print(text)
