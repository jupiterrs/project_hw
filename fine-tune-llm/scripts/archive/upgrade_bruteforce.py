#!/usr/bin/env python3
"""Generate real verification code for stub AIME entries using LLM.

For each stub entry, sends the problem text to an LLM with instructions
to write brute-force Python code that computes the answer. Tests the code
and applies successful upgrades to the trajectory files.
"""
import json, re, subprocess, sys, time, os, warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=DeprecationWarning)
load_dotenv()

DATA_DIR = Path(__file__).parent / "sft-data"
SANDBOX = DATA_DIR / "sandbox.py"
SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."

CODE_GEN_PROMPT = """Write Python code that computes the answer to this AIME problem using brute-force enumeration or direct computation. The answer is {answer}.

IMPORTANT RULES:
1. The code must ACTUALLY COMPUTE the answer from scratch - NOT just set result = {answer}
2. Use brute-force enumeration, search, or direct computation
3. End with: assert result == {answer}, f"Got {{result}}"; print(result)
4. The code must run in under 30 seconds
5. Use only standard library modules (math, itertools, fractions, collections, functools, decimal)
6. Keep it simple and correct

Problem:
{problem}

Write ONLY the Python code, no explanation:"""


def run_code(code, timeout=30):
    sandbox = DATA_DIR / f"sandbox_{os.getpid()}_{id(code)}.py"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sandbox.write_text(code)
        r = subprocess.run([sys.executable, sandbox], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", False
    finally:
        if sandbox.exists():
            sandbox.unlink(missing_ok=True)


def call_llm(problem_text, answer, client, model_id):
    """Call Claude to generate brute-force code."""
    prompt = CODE_GEN_PROMPT.format(answer=answer, problem=problem_text)
    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        code_match = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        if text.startswith('#') or text.startswith('import') or text.startswith('from'):
            return text
        return None
    except Exception as e:
        return f"ERROR: {e}"


def process_entry(args):
    """Process a single stub entry. Returns (fname, idx, answer, code, obs) or None."""
    fname, idx, answer, prob_text, client, model_id = args
    for attempt in range(3):
        generated = call_llm(prob_text, answer, client, model_id)
        if not generated:
            continue
        if isinstance(generated, str) and generated.startswith("ERROR:"):
            continue
        if re.search(r'result\s*=\s*' + re.escape(answer) + r'\s*;?\s*assert', generated):
            time.sleep(1)
            continue
        stdout, stderr, ok = run_code(generated, timeout=30)
        if ok and stdout:
            return (fname, idx, answer, generated, stdout)
        time.sleep(0.5)
    return (fname, idx, answer, None, None)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max', type=int, default=999)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    dry_run = args.dry_run
    max_entries = args.max
    workers = args.workers

    import anthropic
    client = anthropic.Anthropic()
    model_id = "claude-3-5-haiku-20241022"
    print(f"Using model: {model_id}, workers: {workers}")

    stubs = json.load(open('/tmp/aime_stubs.json'))
    print(f"Total stubs: {len(stubs)}")

    to_process = stubs[:max_entries]
    args_list = [(fname, idx, ans, prob, client, model_id) for fname, idx, ans, prob in to_process]

    upgraded = 0
    failed = 0
    results = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_entry, a): a for a in args_list}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            fname, idx, answer, code, obs = future.result()
            if code is not None:
                upgraded += 1
                status = "PASS"
                results[f"({fname}, {idx})"] = {"code": code, "observation": obs, "answer": answer}
                print(f"[{done_count}/{len(to_process)}] {fname} entry {idx} (ans={answer}) PASS", flush=True)
            else:
                failed += 1
                print(f"[{done_count}/{len(to_process)}] {fname} entry {idx} (ans={answer}) FAIL", flush=True)

    # Save results
    with open('/tmp/aime_bf_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    if not dry_run:
        for key, val in results.items():
            fname, idx_str = key.strip("()").split(", ")
            idx = int(idx_str)
            path = DATA_DIR / fname
            entries = []
            with open(path) as f:
                for line in f:
                    entries.append(json.loads(line))

            entry = entries[idx]
            prob_text_actual = None
            sol_text_parts = []
            for m in entry['messages']:
                if m['role'] == 'user' and '<observation>' not in m['content']:
                    prob_text_actual = m['content']
                if m['role'] == 'assistant':
                    c = re.sub(r'<tool>.*?</tool>', '', m['content'], flags=re.DOTALL)
                    c = re.sub(r'<observation>.*?</observation>', '', c, flags=re.DOTALL)
                    c = re.sub(r'<answer>.*?</answer>', '', c, flags=re.DOTALL)
                    c = re.sub(r'^I need to solve this step by step\.\s*', '', c.strip())
                    c = re.sub(r'\s*Let me verify this.*?Python\.\s*$', '', c)
                    c = re.sub(r'\s*The computation confirms.*$', '', c)
                    if c.strip(): sol_text_parts.append(c.strip())

            sol_text = '\n\n'.join(sol_text_parts)
            code = val['code']
            obs = val['observation']
            answer = val['answer']
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
            msgs.append({"role": "user", "content": prob_text_actual or val.get('problem', '')})
            parts = []
            if sol_text: parts.append(sol_text)
            parts.append("Let me verify this computation with Python.")
            parts.append(f"<tool>\n```python\n{code}\n```\n</tool>")
            msgs.append({"role": "assistant", "content": "\n\n".join(parts)})
            msgs.append({"role": "user", "content": f"<observation>\n{obs}\n</observation>"})
            msgs.append({"role": "assistant", "content": f"The computation confirms the answer.\n\n<answer>\n{answer}\n</answer>"})

            entries[idx] = {"messages": msgs}
            with open(path, 'w') as f:
                for e in entries:
                    f.write(json.dumps(e) + '\n')

        print(f"Applied {upgraded} upgrades to trajectory files")

    if SANDBOX.exists():
        SANDBOX.unlink()

    print(f"\n{'='*50}")
    print(f"BRUTE-FORCE UPGRADE SUMMARY {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*50}")
    print(f"Upgraded: {upgraded}")
    print(f"Failed:   {failed}")
    print(f"Remaining stubs: {len(stubs) - upgraded - failed}")


if __name__ == '__main__':
    main()