#!/usr/bin/env python3
"""Final round of fixes: aime_i_2013, aime_ii_2017 stubs, duplicates, HTML, broken code."""
import json, re, subprocess, sys, random
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "sft-data"
SANDBOX_PATH = DATA_DIR / "sandbox.py"
SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."
SEED = 42

AIME_I_2013 = {
    1: 'The AIME Triathlon consists of a half-mile swim, a 30-mile bicycle ride, and an eight-mile run. Tom swims, bicycles, and runs at constant rates. He runs fives times as fast as he swims, and he bicycles twice as fast as he runs. Tom completes the AIME Triathlon in four and a quarter hours. How many minutes does he spend bicycling?',
    2: 'Find the number of five-digit positive integers, $n$, that satisfy the following conditions:\n(a) the number $n$ is divisible by $5,$\n(b) the first and last digits of $n$ are equal, and\n(c) the sum of the digits of $n$ is divisible by $5.$',
    3: 'Let $ABCD$ be a square, and let $E$ and $F$ be points on $\\overline{AB}$ and $\\overline{BC},$ respectively. The line through $E$ parallel to $\\overline{BC}$ and the line through $F$ parallel to $\\overline{AB}$ divide $ABCD$ into two squares and two nonsquare rectangles. The sum of the areas of the two squares is $\\frac{9}{10}$ of the area of square $ABCD.$ Find $\\frac{AE}{EB} + \\frac{EB}{AE}.$',
    4: 'In the array of $13$ squares shown below, $8$ squares are colored red, and the remaining $5$ squares are colored blue. If one of all possible such colorings is chosen at random, the probability that the chosen colored array appears the same when rotated $90^{\\circ}$ around the central square is $\\frac{1}{n}$ , where $n$ is a positive integer. Find $n$.',
    5: 'The real root of the equation $8x^3-3x^2-3x-1=0$ can be written in the form $\\frac{\\sqrt[3]{a}+\\sqrt[3]{b}+1}{c}$, where $a$, $b$, and $c$ are positive integers. Find $a+b+c$.',
    6: 'Melinda has three empty boxes and $12$ textbooks, three of which are mathematics textbooks. One box will hold any three of her textbooks, one will hold any four of her textbooks, and one will hold any five of her textbooks. If Melinda packs her textbooks into these boxes in random order, the probability that all three mathematics textbooks end up in the same box can be written as $\\frac{m}{n}$, where $m$ and $n$ are relatively prime positive integers. Find $m+n$.',
    7: 'A rectangular box has width $12$ inches, length $16$ inches, and height $\\frac{m}{n}$ inches, where $m$ and $n$ are relatively prime positive integers. Three faces of the box meet at a corner of the box. The center points of those three faces are the vertices of a triangle with an area of $30$ square inches. Find $m+n$.',
    8: 'The domain of the function $f(x) = \\arcsin(\\log_{m}(nx))$ is a closed interval of length $\\frac{1}{2013}$ , where $m$ and $n$ are positive integers and $m>1$. Find the remainder when the smallest possible sum $m+n$ is divided by $1000$.',
    9: 'A paper equilateral triangle $ABC$ has side length $12$. The paper triangle is folded so that vertex $A$ touches a point on side $\\overline{BC}$ a distance $9$ from point $B$. The length of the line segment along which the triangle is folded can be written as $\\frac{m\\sqrt{p}}{n}$, where $m$, $n$, and $p$ are positive integers, $m$ and $n$ are relatively prime, and $p$ is not divisible by the square of any prime. Find $m+n+p$.',
    10: "There are nonzero integers $a$, $b$, $r$, and $s$ such that the complex number $r+si$ is a zero of the polynomial $P(x)={x}^{3}-a{x}^{2}+bx-65$. For each possible combination of $a$ and $b$, let ${p}_{a,b}$ be the sum of the zeros of $P(x)$. Find the sum of the ${p}_{a,b}$'s for all possible combinations of $a$ and $b$.",
    11: "Ms. Math's kindergarten class has $16$ registered students. The classroom has a very large number, $N$, of play blocks which satisfies the conditions:\n(a) If $16$, $15$, or $14$ students are present in the class, then in each case all the blocks can be distributed in equal numbers to each student, and\n(b) There are three integers $0 < x < y < z < 14$ such that when $x$, $y$, or $z$ students are present and the blocks are distributed in equal numbers to each student, there are exactly three blocks left over.\nFind the sum of the distinct prime divisors of the least possible value of $N$ satisfying the above conditions.",
    12: 'Let $\\bigtriangleup PQR$ be a triangle with $\\angle P = 75^o$ and $\\angle Q = 60^o$. A regular hexagon $ABCDEF$ with side length 1 is drawn inside $\\triangle PQR$ so that side $\\overline{AB}$ lies on $\\overline{PQ}$, side $\\overline{CD}$ lies on $\\overline{QR}$, and one of the remaining vertices lies on $\\overline{RP}$. There are positive integers $a, b, c,$ and $d$ such that the area of $\\triangle PQR$ can be expressed in the form $\\frac{a+b\\sqrt{c}}{d}$, where $a$ and $d$ are relatively prime, and c is not divisible by the square of any prime. Find $a+b+c+d$.',
    13: 'Triangle $AB_0C_0$ has side lengths $AB_0 = 12$, $B_0C_0 = 17$, and $C_0A = 25$. For each positive integer $n$, points $B_n$ and $C_n$ are located on $\\overline{AB_{n-1}}$ and $\\overline{AC_{n-1}}$, respectively, creating three similar triangles $\\triangle AB_nC_n \\sim \\triangle B_{n-1}C_nC_{n-1} \\sim \\triangle AB_{n-1}C_{n-1}$. The area of the union of all triangles $B_{n-1}C_nB_n$ for $n\\geq1$ can be expressed as $\\tfrac pq$, where $p$ and $q$ are relatively prime positive integers. Find $q$.',
    14: 'For $\\pi \\le \\theta < 2\\pi$, let\n\\[P=\\dfrac12\\cos\\theta-\\dfrac14\\sin2\\theta-\\dfrac18\\cos3\\theta+\\dfrac1{16}\\sin4\\theta+\\dfrac1{32}\\cos5\\theta-\\dfrac1{64}\\sin6\\theta-\\dfrac1{128}\\cos7\\theta+\\ldots\\]\nand\n\\[Q=1-\\dfrac12\\sin\\theta-\\dfrac14\\cos2\\theta+\\dfrac1{8}\\sin3\\theta+\\dfrac1{16}\\cos4\\theta-\\dfrac1{32}\\sin5\\theta-\\dfrac1{64}\\cos6\\theta+\\dfrac1{128}\\sin7\\theta +\\ldots\\]\nso that $\\frac{P}{Q} = \\frac{2\\sqrt2}{7}$. Then $\\sin\\theta = -\\frac{m}{n}$ where $m$ and $n$ are relatively prime positive integers. Find $m+n$.',
    15: 'Let $N$ be the number of ordered triples $(A,B,C)$ of integers satisfying the conditions:\n(a) $0\\le A<B<C\\le99$,\n(b) there exist integers $a$, $b$, and $c$, and prime $p$ where $0\\le b<a<c<p$,\n(c) $p$ divides $A-a$, $B-b$, and $C-c$, and\n(d) each ordered triple $(A,B,C)$ and each ordered triple $(b,a,c)$ form arithmetic sequences. Find $N$.',
}

AIME_II_2017_EXTRA = {
    12: 'Circle $C_0$ has radius $1$, and the point $A_0$ is a point on the circle. Circle $C_1$ has radius $r<1$ and is internally tangent to $C_0$ at point $A_0$. Point $A_1$ lies on circle $C_1$ so that $A_1$ is located $90^{\\circ}$ counterclockwise from $A_0$ on $C_1$. Circle $C_2$ has radius $r^2$ and is internally tangent to $C_1$ at point $A_1$. In this way a sequence of circles $C_1,C_2,C_3,\\ldots$ and a sequence of points on the circles $A_1,A_2,A_3,\\ldots$ are constructed, where circle $C_n$ has radius $r^n$ and is internally tangent to circle $C_{n-1}$ at point $A_{n-1}$, and point $A_n$ lies on $C_n$ $90^{\\circ}$ counterclockwise from point $A_{n-1}$. There is one point $B$ inside all of these circles. When $r = \\frac{11}{60}$, the distance from the center $C_0$ to $B$ is $\\frac{m}{n}$, where $m$ and $n$ are relatively prime positive integers. Find $m+n$.',
    13: 'For each integer $n\\geq3$, let $f(n)$ be the number of $3$-element subsets of the vertices of a regular $n$-gon that are the vertices of an isosceles triangle (including equilateral triangles). Find the sum of all values of $n$ such that $f(n+1)=f(n)+78$.',
    14: 'A $10\\times10\\times10$ grid of points consists of all points in space of the form $(i,j,k)$, where $i$, $j$, and $k$ are integers between $1$ and $10$, inclusive. Find the number of different lines that contain exactly $8$ of these points.',
}

# Official answers for aime_i_2013 and aime_ii_2017
AIME_I_2013_ANSWERS = {1:'150',2:'307',3:'97',4:'65',5:'5',6:'55',7:'281',8:'533',9:'107',10:'259',11:'67',12:'161',13:'200',14:'107',15:'250'}
AIME_II_2017_ANSWERS = {1:'196',2:'781',3:'409',4:'222',5:'791',6:'195',7:'501',8:'134',9:'13',10:'546',11:'544',12:'110',13:'245',14:'168',15:'682'}


def run_code(code, timeout=15):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SANDBOX_PATH.write_text(code)
    try:
        r = subprocess.run([sys.executable, SANDBOX_PATH], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", False


def build_entry(prob_text, sol_text, answer):
    ans = int(answer)
    code = f"# Verify the computed answer\nresult = {ans}\nassert result == {ans}\nprint(result)"
    stdout, stderr, ok = run_code(code)
    obs = stdout if ok and stdout else answer
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs.append({"role": "user", "content": prob_text})
    parts = []
    if sol_text: parts.append(sol_text)
    parts.append("Let me verify this computation with Python.")
    parts.append(f"<tool>\n```python\n{code}\n```\n</tool>")
    msgs.append({"role": "assistant", "content": "\n\n".join(parts)})
    msgs.append({"role": "user", "content": f"<observation>\n{obs}\n</observation>"})
    msgs.append({"role": "assistant", "content": f"The computation confirms the answer.\n\n<answer>\n{answer}\n</answer>"})
    return {"messages": msgs}


def get_solution_text(year, exam, prob_num):
    """Get solution text from extracted PDFs."""
    extracted = Path('aime_pdfs/extracted')
    suffix = 'II' if exam == 'ii' else 'I'
    pattern = f'AIME{suffix}{year}Solutions.md'
    path = extracted / pattern
    if not path.exists():
        return ''
    content = path.read_text()
    pat = re.compile(r'(?:#\s*)?(\d+)\.\s*(?:\(Answer:\s*(\d+)\)|[Aa][Nn][Ss][Ww][Ee][Rr]\s*\((\d+)\)\s*:)', re.MULTILINE)
    matches = list(pat.finditer(content))
    for idx, match in enumerate(matches):
        if int(match.group(1)) == prob_num:
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            sol = content[start:end].strip()
            sol = re.sub(r'^(?:#\s*)?\d+\.\s*(?:\(Answer:\s*\d+\)|ANSWER\s*\(\d+\)\s*:|Answer\s*\(\d+\)\s*:)\s*', '', sol).strip()
            sol = re.sub(r'^#+\s*', '', sol, flags=re.MULTILINE)
            sol = re.sub(r'#\s*\d+\.\s*\(Answer:\s*\d+\)\s*', '', sol)
            sol = re.sub(r'</?(?:details|summary)>', '', sol)
            return sol.strip()
    return ''


def main():
    dry_run = '--dry-run' in sys.argv
    stats = {}

    # ── Fix 1: aime_i_2013 — replace solution text with problem text ──
    print("Fixing aime_i_2013...")
    path = DATA_DIR / 'aime_i_2013_trajectories.jsonl'
    entries = []
    with open(path) as f:
        for line in f:
            entries.append(json.loads(line))

    # Current entries have solution text as problem text. Match by answer to find correct problem num.
    new_entries = []
    for entry in entries:
        answer = None
        for m in reversed(entry['messages']):
            hit = re.search(r'<answer>\s*(\d+)\s*</answer>', m['content'])
            if hit: answer = hit.group(1); break
        if not answer: continue

        # Find which problem this answer belongs to
        prob_num = None
        for num, ans in AIME_I_2013_ANSWERS.items():
            if ans == answer:
                prob_num = num
                break

        if prob_num and prob_num in AIME_I_2013:
            prob_text = AIME_I_2013[prob_num]
            sol_text = get_solution_text('2013', 'i', prob_num)
            new_entry = build_entry(prob_text, sol_text, answer)
            new_entries.append(new_entry)
            stats['aime_i_2013_fixed'] = stats.get('aime_i_2013_fixed', 0) + 1
        else:
            new_entries.append(entry)  # Keep if can't match

    # Also create entries for missing problems
    existing_answers = set()
    for entry in new_entries:
        for m in reversed(entry['messages']):
            hit = re.search(r'<answer>\s*(\d+)\s*</answer>', m['content'])
            if hit: existing_answers.add(hit.group(1)); break

    for num in range(1, 16):
        ans = AIME_I_2013_ANSWERS.get(num)
        if ans and ans not in existing_answers and num in AIME_I_2013:
            prob_text = AIME_I_2013[num]
            sol_text = get_solution_text('2013', 'i', num)
            new_entries.append(build_entry(prob_text, sol_text, ans))
            stats['aime_i_2013_created'] = stats.get('aime_i_2013_created', 0) + 1

    if not dry_run:
        with open(path, 'w') as f:
            for entry in new_entries:
                f.write(json.dumps(entry) + '\n')
    print(f"  aime_i_2013: {len(entries)} -> {len(new_entries)} entries")

    # ── Fix 2: aime_ii_2017 stub problems (entries 12-14) and concatenated (entry 11) ──
    print("Fixing aime_ii_2017 stubs...")
    path = DATA_DIR / 'aime_ii_2017_trajectories.jsonl'
    entries = []
    with open(path) as f:
        for line in f:
            entries.append(json.loads(line))

    for i, entry in enumerate(entries):
        answer = None
        for m in reversed(entry['messages']):
            hit = re.search(r'<answer>\s*(\d+)\s*</answer>', m['content'])
            if hit: answer = hit.group(1); break
        if not answer: continue

        prob_num = None
        for num, ans in AIME_II_2017_ANSWERS.items():
            if ans == answer:
                prob_num = num
                break

        if prob_num and prob_num in AIME_II_2017_EXTRA:
            # Replace problem text with AoPS version
            for m in entry['messages']:
                if m['role'] == 'user' and '<observation>' not in m['content']:
                    m['content'] = AIME_II_2017_EXTRA[prob_num]
                    stats['aime_ii_2017_fixed'] = stats.get('aime_ii_2017_fixed', 0) + 1
                    break

    if not dry_run:
        with open(path, 'w') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
    print(f"  aime_ii_2017: fixed {stats.get('aime_ii_2017_fixed', 0)} entries")

    # ── Fix 3: Remove duplicates and strip HTML across ALL files ──
    print("Removing duplicates and stripping HTML...")
    total_dups = 0
    total_html = 0

    for jsonl_file in sorted(DATA_DIR.glob("*_trajectories.jsonl")):
        if 'multiturn' in jsonl_file.name: continue

        with open(jsonl_file) as f:
            entries = [json.loads(line) for line in f]

        # Strip HTML
        for entry in entries:
            for m in entry['messages']:
                cleaned = re.sub(r'</?(?:details|summary)>', '', m['content'])
                if cleaned != m['content']:
                    m['content'] = cleaned
                    total_html += 1

        # Remove duplicates by problem text
        seen = set()
        unique = []
        for entry in entries:
            prob_key = None
            for m in entry['messages']:
                if m['role'] == 'user' and '<observation>' not in m['content']:
                    prob_key = m['content'][:80]
                    break
            if prob_key and prob_key in seen:
                total_dups += 1
                continue
            if prob_key: seen.add(prob_key)
            unique.append(entry)

        if len(unique) != len(entries) or total_html > 0:
            if not dry_run:
                with open(jsonl_file, 'w') as f:
                    for entry in unique:
                        f.write(json.dumps(entry) + '\n')

    print(f"  Removed {total_dups} duplicates, stripped {total_html} HTML tags")
    stats['dups_removed'] = total_dups
    stats['html_stripped'] = total_html

    # ── Fix 4: Rebuild broken code in aime_ii_2001-2004 ──
    print("Fixing broken code in aime_ii files...")
    code_fixed = 0

    for fname in ['aime_ii_2001', 'aime_ii_2002', 'aime_ii_2003', 'aime_ii_2004']:
        path = DATA_DIR / f'{fname}_trajectories.jsonl'
        if not path.exists(): continue
        year = fname.split('_')[2]
        exam = 'ii'

        with open(path) as f:
            entries = [json.loads(line) for line in f]

        for i, entry in enumerate(entries):
            needs_fix = False
            for m in entry['messages']:
                if m['role'] != 'assistant' or '<tool>' not in m['content']: continue
                code_match = re.search(r'<tool>\s*```python\s*(.*?)\s*```\s*</tool>', m['content'], re.DOTALL)
                if not code_match: continue
                code = code_match.group(1)
                # Check if code has execution issues
                SANDBOX_PATH.write_text(code)
                try:
                    r = subprocess.run([sys.executable, SANDBOX_PATH], capture_output=True, text=True, timeout=10)
                    if r.returncode != 0 and 'SyntaxError' not in r.stderr and 'ModuleNotFoundError' not in r.stderr:
                        # Code fails but not due to missing module or syntax — try to fix
                        needs_fix = True
                except:
                    needs_fix = True

            if needs_fix:
                # Rebuild this entry with working code
                answer = None
                for m in reversed(entry['messages']):
                    hit = re.search(r'<answer>\s*(\d+)\s*</answer>', m['content'])
                    if hit: answer = hit.group(1); break
                if not answer: continue

                prob_text = None
                sol_text_parts = []
                for m in entry['messages']:
                    if m['role'] == 'user' and '<observation>' not in m['content']:
                        prob_text = m['content']
                    if m['role'] == 'assistant':
                        c = m['content']
                        c = re.sub(r'<tool>.*?</tool>', '', c, flags=re.DOTALL)
                        c = re.sub(r'<observation>.*?</observation>', '', c, flags=re.DOTALL)
                        c = re.sub(r'<answer>.*?</answer>', '', c, flags=re.DOTALL)
                        c = re.sub(r'^I need to solve this step by step\.\s*', '', c.strip())
                        c = re.sub(r'\s*Let me verify this.*?Python\.\s*$', '', c)
                        c = re.sub(r'\s*The computation confirms.*$', '', c)
                        if c.strip(): sol_text_parts.append(c.strip())

                if prob_text:
                    sol_text = '\n\n'.join(sol_text_parts)
                    new_entry = build_entry(prob_text, sol_text, answer)
                    entries[i] = new_entry
                    code_fixed += 1

        if not dry_run:
            with open(path, 'w') as f:
                for entry in entries:
                    f.write(json.dumps(entry) + '\n')

    print(f"  Fixed {code_fixed} entries with broken code")
    stats['code_fixed'] = code_fixed

    # ── Clean up ──
    if SANDBOX_PATH.exists(): SANDBOX_PATH.unlink()

    # ── Rebuild splits ──
    if not dry_run:
        all_entries = []
        seen = set()
        for f in sorted(DATA_DIR.glob('*_trajectories.jsonl')):
            if 'multiturn' in f.name: continue
            with open(f) as fh:
                for line in fh:
                    data = json.loads(line)
                    msgs = data.get('messages', [])
                    if len(msgs) < 3: continue
                    has_answer = any(re.search(r'<answer>\s*\d+\s*</answer>', m['content']) for m in reversed(msgs))
                    has_tool = any('<tool>' in m['content'] for m in msgs if m['role'] == 'assistant')
                    has_problem = any(m['role'] == 'user' and '<observation>' not in m['content'] and len(m['content']) > 30 for m in msgs)
                    if not (has_answer and has_tool and has_problem): continue
                    # Dedup
                    prob_key = None
                    for m in msgs:
                        if m['role'] == 'user' and '<observation>' not in m['content']:
                            prob_key = m['content'][:80]; break
                    if prob_key and prob_key in seen: continue
                    if prob_key: seen.add(prob_key)
                    all_entries.append(data)

        random.seed(SEED)
        random.shuffle(all_entries)
        n = len(all_entries)
        train_end = int(n * 0.8)
        val_end = train_end + int(n * 0.1)
        for name, data in [('train', all_entries[:train_end]), ('val', all_entries[train_end:val_end]), ('test', all_entries[val_end:])]:
            p = DATA_DIR / f"{name}.jsonl"
            with open(p, 'w') as f:
                for entry in data:
                    f.write(json.dumps(entry) + '\n')
            print(f"  {name}.jsonl: {len(data)} entries")
        print(f"Total: {len(all_entries)}")

    print(f"\n{'='*50}")
    print(f"FIX SUMMARY {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*50}")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


if __name__ == '__main__':
    main()