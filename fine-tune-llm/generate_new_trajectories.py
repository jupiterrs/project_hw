#!/usr/bin/env python3
"""Generate AIME trajectories for 2019-2025 using Sonnet with brute-force code.

Unlike the old pipeline (stub code → upgrade), this generates proper code
directly by giving Sonnet the answer and asking it to write brute-force code.
"""
import json, re, subprocess, sys, time, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

warnings_ok = False
try:
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings_ok = True
except:
    pass

load_dotenv()

DATA_DIR = Path(__file__).parent / "sft-data"
SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."

CODE_PROMPT = """You are solving an AIME math competition problem. The answer is {answer}.

Write Python code that computes this answer from scratch using brute-force or direct computation.

STRATEGY:
- For counting problems: enumerate all possibilities and count those meeting the condition
- For number theory: iterate and check conditions
- For algebra: solve systematically with brute force
- For geometry: use coordinate geometry with Fraction for exact arithmetic
- For probability: enumerate all outcomes
- Use only: math, itertools, fractions, collections, functools, decimal

CRITICAL RULES:
- Do NOT just write "result = {answer}". You must actually compute it.
- Use Fraction for exact rational arithmetic
- End with: assert result == {answer}, f"Got {{result}}"; print(result)
- Must run in under 30 seconds
- Keep it simple and correct

Problem:
{problem}

Write ONLY the Python code, no explanation:"""

SOLUTION_PROMPT = """You are solving an AIME math competition problem. The answer is {answer}.

Write a step-by-step mathematical solution, then verify with Python code.

Problem:
{problem}

Solution:"""


def run_code(code, timeout=30):
    sandbox = DATA_DIR / f"sb_new_{os.getpid()}_{hash(code) & 0xFFFFFF}.py"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sandbox.write_text(code)
        r = subprocess.run([sys.executable, sandbox], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", False
    finally:
        sandbox.unlink(missing_ok=True)


def call_llm_code(prob_text, answer, client, model_id):
    prompt = CODE_PROMPT.format(answer=answer, problem=prob_text)
    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if not text:
            return None
        code_match = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        if text.startswith('#') or text.startswith('import') or text.startswith('from'):
            return text
        return None
    except Exception as e:
        return f"ERROR: {e}"


def call_llm_solution(prob_text, answer, client, model_id):
    prompt = SOLUTION_PROMPT.format(answer=answer, problem=prob_text)
    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"ERROR: {e}"


def process_entry(args):
    key, num, prob_text, answer, solution, client, model_id, max_attempts = args
    # Generate code
    code = None
    obs = None
    for attempt in range(max_attempts):
        generated = call_llm_code(prob_text, answer, client, model_id)
        if not generated or (isinstance(generated, str) and generated.startswith("ERROR:")):
            time.sleep(0.5)
            continue
        if re.search(r'result\s*=\s*' + re.escape(answer) + r'\s*$', generated, re.MULTILINE):
            time.sleep(0.3)
            continue
        stdout, stderr, ok = run_code(generated, timeout=30)
        if ok and stdout:
            code = generated
            obs = stdout
            break
        time.sleep(0.3)

    if code is None:
        return (key, num, answer, None, None, None)

    # Generate or use solution text
    if solution and len(solution) > 50:
        sol_text = solution
        # Clean up the solution
        sol_text = re.sub(r'\\boxed\{[^}]+\}', '', sol_text)
        sol_text = re.sub(r'\\begin\{align.*?\}.*?\\end\{align.*?\}', '', sol_text, flags=re.DOTALL)
    else:
        sol_text = None

    return (key, num, answer, code, obs, sol_text)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--attempts', type=int, default=5)
    parser.add_argument('--model', default='claude-sonnet-4-5-20250514')
    parser.add_argument('--max', type=int, default=999)
    args = parser.parse_args()

    import anthropic
    client = anthropic.Anthropic()
    model_id = args.model
    print(f"TRAJECTORY GEN: model={model_id}, workers={args.workers}, attempts={args.attempts}")

    new_data = json.load(open('/tmp/aime_new_years.json'))
    print(f"Contests: {len(new_data)}, Total problems: {sum(len(v) for v in new_data.values())}")

    # Build work items
    work_items = []
    for key, problems in sorted(new_data.items()):
        for p in problems:
            if p.get('answer'):
                work_items.append((
                    key, p['number'], p['text'], p['answer'],
                    p.get('solution', ''), client, model_id, args.attempts
                ))

    work_items = work_items[:args.max]
    print(f"Processing {len(work_items)} problems")

    upgraded = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_entry, w): w for w in work_items}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            key, num, answer, code, obs, sol_text = future.result()
            if code is not None:
                upgraded += 1
                print(f"[{done_count}/{len(work_items)}] {key} #{num} (ans={answer}) PASS", flush=True)
            else:
                failed += 1
                print(f"[{done_count}/{len(work_items)}] {key} #{num} (ans={answer}) FAIL", flush=True)

    print(f"\n{'='*50}")
    print(f"TRAJECTORY GEN SUMMARY {'(DRY RUN)' if args.dry_run else ''}")
    print(f"{'='*50}")
    print(f"Upgraded: {upgraded}")
    print(f"Failed:   {failed}")


if __name__ == '__main__':
    main()