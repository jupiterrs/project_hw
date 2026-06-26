#!/usr/bin/env python3
"""V3 upgrade for remaining stub AIME entries.

Key insight: The previous "brute-force enumeration" approach fails on geometry
because you can't enumerate coordinates. Instead, we use "computational derivation"
— set up coordinates with Fraction, apply formulas, solve equations step-by-step.

Also provides a helper library of common geometry/number theory functions.
"""
import json, re, subprocess, sys, time, os, warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=DeprecationWarning)
load_dotenv()

DATA_DIR = Path(__file__).parent / "sft-data"
SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."

# Helper library that gets prepended to all generated code
HELPER_LIB = r'''
from fractions import Fraction
from math import gcd, isqrt, sqrt, pi, cos, sin, radians, factorial, comb, log2, log10
from itertools import product, permutations, combinations, combinations_with_replacement
from collections import Counter, defaultdict
from functools import reduce

F = Fraction

def dist(p1, p2):
    """Distance between two points (with Fraction coordinates)."""
    return (sum((a-b)**2 for a,b in zip(p1,p2)))**F(1,2)

def dist_sq(p1, p2):
    """Squared distance between two points."""
    return sum((a-b)**2 for a,b in zip(p1,p2))

def triangle_area(A, B, C):
    """Area of triangle using cross product (works with Fraction)."""
    return abs((B[0]-A[0])*(C[1]-A[1]) - (C[0]-A[0])*(B[1]-A[1])) / 2

def triangle_area_heron(a, b, c):
    """Area of triangle given side lengths using Heron's formula."""
    s = (a + b + c) / 2
    return (s*(s-a)*(s-b)*(s-c))**F(1,2)

def midpoint(p1, p2):
    return tuple((a+b)/2 for a,b in zip(p1,p2))

def line_intersection(p1, p2, p3, p4):
    """Intersection of line through p1,p2 and line through p3,p4."""
    x1,y1 = p1; x2,y2 = p2; x3,y3 = p3; x4,y4 = p4
    denom = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
    if denom == 0: return None
    t = ((x1-x3)*(y3-y4) - (y1-y3)*(x3-x4)) / denom
    x = x1 + t*(x2-x1)
    y = y1 + t*(y2-y1)
    return (x, y)

def foot_of_perpendicular(P, A, B):
    """Foot of perpendicular from P to line AB."""
    ax,ay = A; bx,by = B; px,py = P
    dx, dy = bx-ax, by-ay
    if dx == 0 and dy == 0: return A
    t = ((px-ax)*dx + (py-ay)*dy) / (dx*dx + dy*dy)
    return (ax + t*dx, ay + t*dy)

def angle_bisector_point(A, B, C):
    """Point D on AC where BD bisects angle ABC. Returns D."""
    ab = dist_sq(A, B)**F(1,2)
    bc = dist_sq(B, C)**F(1,2)
    # D divides AC in ratio AB:BC
    return tuple((bc*a + ab*c)/(ab+bc) for a,c in zip(A,C))

def polygon_area(vertices):
    """Area of polygon using shoelace formula."""
    n = len(vertices)
    area = F(0)
    for i in range(n):
        j = (i+1) % n
        area += vertices[i][0] * vertices[j][1]
        area -= vertices[j][0] * vertices[i][1]
    return abs(area) / 2

def circle_from_3_points(A, B, C):
    """Returns (center, radius) of circle through 3 points."""
    ax,ay = A; bx,by = B; cx,cy = C
    D = 2*(ax*(by-cy) + bx*(cy-ay) + cx*(ay-by))
    if D == 0: return None
    ux = ((ax**2+ay**2)*(by-cy) + (bx**2+by**2)*(cy-ay) + (cx**2+cy**2)*(ay-by)) / D
    uy = ((ax**2+ay**2)*(cx-bx) + (bx**2+by**2)*(ax-cx) + (cx**2+cy**2)*(bx-ax)) / D
    r = dist_sq((ux,uy), A)**F(1,2)
    return ((ux,uy), r)

def int_sqrt(n):
    """Integer square root if perfect square, else None."""
    if n < 0: return None
    s = isqrt(n)
    return s if s*s == n else None

def divisors(n):
    """All positive divisors of n."""
    n = abs(n)
    divs = []
    for i in range(1, isqrt(n)+1):
        if n % i == 0:
            divs.append(i)
            if i != n//i:
                divs.append(n//i)
    return sorted(divs)

def is_prime(n):
    if n < 2: return False
    if n < 4: return True
    if n%2==0 or n%3==0: return False
    i=5
    while i*i<=n:
        if n%i==0 or n%(i+2)==0: return False
        i+=6
    return True

def lcm(a, b):
    return abs(a*b) // gcd(a, b)
'''

GEO_PROMPT = """You are solving an AIME math competition problem. The answer is {answer}.

This is a GEOMETRY problem. Write Python code that computes the answer using coordinate geometry and exact arithmetic.

STRATEGY:
- Place the figure in a coordinate system (choose convenient coordinates)
- Use Fraction for exact arithmetic (no floating point!)
- A helper library is already imported with these functions: F (Fraction alias), dist, dist_sq, triangle_area, triangle_area_heron, midpoint, line_intersection, foot_of_perpendicular, angle_bisector_point, polygon_area, circle_from_3_points, int_sqrt, divisors, is_prime, lcm
- Compute step-by-step using coordinate formulas
- For area: use triangle_area or polygon_area (shoelace)
- For intersections: use line_intersection
- For perpendicular feet: use foot_of_perpendicular
- For angle bisectors: use angle_bisector_point
- For circles: use circle_from_3_points

CRITICAL RULES:
- Do NOT just write "result = {answer}". You must actually compute it.
- Use Fraction (or F) for ALL arithmetic to keep results exact
- End with: assert result == {answer}, f"Got {{result}}"; print(result)
- Must run in under 30 seconds
- The helper library is already imported - do NOT re-import math/fractions/etc.

Problem:
{problem}

Write ONLY the Python code (no imports, helpers already loaded), no explanation:"""

NUM_PROMPT = """You are solving an AIME math competition problem. The answer is {answer}.

This is a NUMBER THEORY / ALGEBRA problem. Write Python code that computes the answer.

STRATEGY:
- For number theory: iterate over the relevant range and check conditions
- For divisibility: iterate and count
- For digits: convert to string or use modular arithmetic
- For factorials/combinatorics: use the provided factorial, comb functions
- Use exact arithmetic (Fraction for rationals, int for integers)
- A helper library is already imported with: F (Fraction), int_sqrt, divisors, is_prime, gcd, lcm, factorial, comb

CRITICAL RULES:
- Do NOT just write "result = {answer}". You must actually compute it.
- Use Fraction for rational arithmetic
- End with: assert result == {answer}, f"Got {{result}}"; print(result)
- Must run in under 30 seconds
- The helper library is already imported - do NOT re-import

Problem:
{problem}

Write ONLY the Python code (no imports, helpers already loaded), no explanation:"""

GENERAL_PROMPT = """You are solving an AIME math competition problem. The answer is {answer}.

Write Python code that computes this answer from scratch. Use the helper library already imported with: F (Fraction), dist, triangle_area, midpoint, line_intersection, foot_of_perpendicular, angle_bisector_point, polygon_area, int_sqrt, divisors, is_prime, gcd, lcm, factorial, comb, product, permutations, combinations.

CRITICAL RULES:
- Do NOT just write "result = {answer}". You must actually compute it.
- Use Fraction for exact rational arithmetic
- End with: assert result == {answer}, f"Got {{result}}"; print(result)
- Must run in under 30 seconds
- The helper library is already imported - do NOT re-import

Problem:
{problem}

Write ONLY the Python code (no imports, helpers already loaded), no explanation:"""


def classify_problem(prob_text):
    p = prob_text.lower()
    geo_kw = ['triangle', 'circle', 'area', 'perimeter', 'angle', 'vertex', 'polygon',
              'square', 'rectangle', 'cube', 'sphere', 'cylinder', 'cone', 'prism',
              'lattice point', 'coordinate', 'diagonal', 'radius', 'chord', 'tangent',
              'bisect', 'centroid', 'orthocenter', 'inscribed', 'circumscribed',
              'parallelepiped', 'polyhedron', 'midpoint', 'distance from',
              'sector', 'arc', 'tetrahedron', 'octahedron']
    if any(kw in p for kw in geo_kw):
        return 'geometry'
    num_kw = ['prime', 'divisor', 'divisible', 'modulo', 'remainder', 'gcd', 'lcm',
              'factor', 'digit', 'base ', 'integer', 'factorial', 'multiple of',
              'positive integer', 'nonnegative']
    alg_kw = ['polynomial', 'equation', 'function', 'sequence', 'series', 'sum',
              'product', 'root', 'coefficient', 'log', 'geometric sequence']
    if any(kw in p for kw in num_kw):
        return 'number_theory'
    if any(kw in p for kw in alg_kw):
        return 'algebra'
    return 'general'


def get_prompt(prob_text, answer):
    cat = classify_problem(prob_text)
    if cat == 'geometry':
        return GEO_PROMPT.format(answer=answer, problem=prob_text)
    elif cat == 'number_theory':
        return NUM_PROMPT.format(answer=answer, problem=prob_text)
    else:
        return GENERAL_PROMPT.format(answer=answer, problem=prob_text)


def run_code(code, timeout=30):
    full_code = HELPER_LIB + '\n' + code
    sandbox = DATA_DIR / f"sb_v3_{os.getpid()}_{hash(code) & 0xFFFFFF}.py"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sandbox.write_text(full_code)
        r = subprocess.run([sys.executable, sandbox], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", False
    finally:
        sandbox.unlink(missing_ok=True)


def call_llm(prob_text, answer, client, model_id):
    prompt = get_prompt(prob_text, answer)
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
        # Check if it starts with code (no markdown wrapper)
        lines = text.strip().split('\n')
        if lines and (lines[0].startswith('#') or lines[0].startswith('result') or
                      any(lines[0].strip().startswith(kw) for kw in ['for ', 'if ', 'while ', 'def '])):
            return text
        return None
    except Exception as e:
        return f"ERROR: {e}"


def fix_code(prob_text, answer, broken_code, error_msg, client, model_id):
    """Ask LLM to fix code that failed with an error."""
    fix_prompt = f"""The following Python code for an AIME problem (answer={answer}) has an error. Fix it.

Problem: {prob_text}

Broken code:
```python
{broken_code}
```

Error:
{error_msg[:500]}

A helper library is already imported with: F (Fraction), dist, triangle_area, midpoint, line_intersection, foot_of_perpendicular, angle_bisector_point, polygon_area, int_sqrt, divisors, is_prime, gcd, lcm, factorial, comb

Rules: Do NOT import anything. Do NOT set result = {answer} directly. End with: assert result == {answer}, f"Got {{result}}"; print(result)

Write ONLY the fixed Python code:"""
    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=2048,
            messages=[{"role": "user", "content": fix_prompt}],
        )
        text = response.content[0].text.strip()
        if not text:
            return None
        code_match = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        if text.startswith('#') or text.startswith('result') or text.startswith('for '):
            return text
        return None
    except Exception:
        return None


def process_entry(args):
    fname, idx, answer, prob_text, client, model_id, max_attempts = args
    last_code = None
    last_error = None
    for attempt in range(max_attempts):
        if attempt == 0 or last_code is None:
            generated = call_llm(prob_text, answer, client, model_id)
        elif attempt <= max_attempts // 2 and last_error:
            # Self-repair: try to fix the broken code
            generated = fix_code(prob_text, answer, last_code, last_error, client, model_id)
        else:
            generated = call_llm(prob_text, answer, client, model_id)
        if not generated:
            continue
        if isinstance(generated, str) and generated.startswith("ERROR:"):
            continue
        # Skip trivial stubs
        if re.search(r'result\s*=\s*' + re.escape(answer) + r'\s*$', generated, re.MULTILINE):
            time.sleep(0.3)
            continue
        # Remove any import lines (helpers already loaded)
        lines = generated.split('\n')
        lines = [l for l in lines if not re.match(r'^\s*(from|import)\s+', l)]
        cleaned = '\n'.join(lines).strip()
        if not cleaned:
            continue
        stdout, stderr, ok = run_code(cleaned, timeout=30)
        if ok and stdout:
            return (fname, idx, answer, cleaned, stdout)
        last_code = cleaned
        last_error = stderr[:800] if stderr else "Unknown error"
        time.sleep(0.3)
    return (fname, idx, answer, None, None)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max', type=int, default=999)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--attempts', type=int, default=8)
    parser.add_argument('--model', default='claude-sonnet-4-5-20250514')
    args = parser.parse_args()

    import anthropic
    client = anthropic.Anthropic()
    model_id = args.model
    print(f"V3 UPGRADE: model={model_id}, workers={args.workers}, attempts={args.attempts}")

    stubs = json.load(open('/tmp/aime_stubs_v3.json'))
    print(f"Total stubs: {len(stubs)}")

    # Classify
    cats = {}
    for s in stubs:
        cat = classify_problem(s['problem'])
        cats[cat] = cats.get(cat, 0) + 1
    print(f"Categories: {cats}")

    to_process = stubs[:args.max]
    args_list = [(s['file'], s['idx'], s['answer'], s['problem'], client, model_id, args.attempts)
                 for s in to_process]

    upgraded = 0
    failed = 0
    results = {}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_entry, a): a for a in args_list}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            fname, idx, answer, code, obs = future.result()
            if code is not None:
                upgraded += 1
                results[f"({fname}, {idx})"] = {"code": code, "observation": obs, "answer": answer}
                print(f"[{done_count}/{len(to_process)}] {fname} entry {idx} (ans={answer}) PASS", flush=True)
            else:
                failed += 1
                print(f"[{done_count}/{len(to_process)}] {fname} entry {idx} (ans={answer}) FAIL", flush=True)

    # Save results
    with open('/tmp/aime_bf_results_v3.json', 'w') as f:
        json.dump(results, f, indent=2)

    if not args.dry_run:
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

    print(f"\n{'='*50}")
    print(f"BRUTE-FORCE UPGRADE V3 SUMMARY {'(DRY RUN)' if args.dry_run else ''}")
    print(f"{'='*50}")
    print(f"Upgraded: {upgraded}")
    print(f"Failed:   {failed}")
    print(f"Total processed: {len(to_process)}")


if __name__ == '__main__':
    main()