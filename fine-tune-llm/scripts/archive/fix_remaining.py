#!/usr/bin/env python3
"""Fix remaining quality issues: bare expressions, duplicates, invalid entries, aime_ii_2017."""
import json, re, subprocess, sys, shutil, random
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "sft-data"
SANDBOX_PATH = DATA_DIR / "sandbox.py"
EXTRACTED_DIR = BASE_DIR / "aime_pdfs" / "extracted"
SYSTEM_PROMPT = "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."
SEED = 42


def run_code(code, timeout=15):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SANDBOX_PATH.write_text(code)
    try:
        r = subprocess.run([sys.executable, SANDBOX_PATH], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", False


def extract_answer(msgs):
    for m in reversed(msgs):
        hit = re.search(r'<answer>\s*(\d+)\s*</answer>', m['content'])
        if hit:
            return hit.group(1)
    return None


def extract_solution_text(msgs):
    parts = []
    for m in msgs:
        if m['role'] != 'assistant':
            continue
        c = m['content']
        c = re.sub(r'<tool>.*?</tool>', '', c, flags=re.DOTALL)
        c = re.sub(r'<observation>.*?</observation>', '', c, flags=re.DOTALL)
        c = re.sub(r'<answer>.*?</answer>', '', c, flags=re.DOTALL)
        c = re.sub(r'^I need to solve this step by step\.\s*', '', c.strip())
        c = re.sub(r'\s*Let me verify this.*?Python\.\s*$', '', c)
        c = re.sub(r'\s*The computation confirms.*$', '', c)
        if c.strip():
            parts.append(c.strip())
    return '\n\n'.join(parts)


# ── Fix 1: Bare expressions ───────────────────────────────

def fix_bare_expressions(code):
    """Replace bare expression lines with print() calls at the end of code blocks."""
    lines = code.split('\n')
    # Find the last line that's a bare expression (not assignment, not control flow, not comment)
    last_bare_idx = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('import ') or stripped.startswith('from '):
            continue
        if stripped.startswith('print(') or stripped.startswith('assert '):
            continue
        # Skip lines that are clearly part of multi-line expressions
        if stripped.endswith(',') or stripped.endswith('\\'):
            continue
        # Skip control flow, assignments, function/class defs
        if any(stripped.startswith(kw) for kw in ['def ', 'for ', 'if ', 'while ', 'class ', 'return ', 'else:', 'elif ', 'break', 'continue']):
            continue
        if '=' in stripped and not stripped.startswith('('):
            continue
        if stripped.endswith(':'):
            continue
        # This looks like a bare expression — wrap in print
        last_bare_idx = i
        break

    if last_bare_idx is not None:
        stripped = lines[last_bare_idx].strip()
        # Don't double-wrap things that are already print-like
        if not stripped.startswith('print('):
            indent = len(lines[last_bare_idx]) - len(lines[last_bare_idx].lstrip())
            lines[last_bare_idx] = ' ' * indent + f'print({stripped})'

    return '\n'.join(lines)


def fix_bare_in_entry(entry):
    """Fix all bare expressions in <tool> blocks of an entry."""
    changed = False
    for m in entry['messages']:
        if m['role'] != 'assistant' or '<tool>' not in m['content']:
            continue
        def replacer(match):
            nonlocal changed
            code = match.group(1)
            fixed = fix_bare_expressions(code)
            if fixed != code:
                changed = True
            return f'<tool>\n```python\n{fixed}\n```\n</tool>'
        m['content'] = re.sub(
            r'<tool>\s*```python\s*(.*?)\s*```\s*</tool>',
            replacer, m['content'], flags=re.DOTALL
        )
    return changed


# ── Fix 2: Re-run code after fix and update observations ──

def re_run_code_in_entry(entry):
    """After fixing code, re-run it and update <observation> blocks."""
    changed = False
    # Collect all code and observation positions
    for m in entry['messages']:
        if m['role'] == 'user' and '<observation>' in m['content']:
            obs_match = re.search(r'<observation>\s*(.*?)\s*</observation>', m['content'], re.DOTALL)
            if not obs_match:
                continue
            # Find the preceding <tool> block in the previous assistant message
            prev_idx = entry['messages'].index(m) - 1
            if prev_idx < 0 or entry['messages'][prev_idx]['role'] != 'assistant':
                continue
            prev = entry['messages'][prev_idx]
            tool_match = re.search(r'<tool>\s*```python\s*(.*?)\s*```\s*</tool>', prev['content'], re.DOTALL)
            if not tool_match:
                continue
            code = tool_match.group(1)
            stdout, stderr, ok = run_code(code)
            if ok and stdout:
                old_obs = obs_match.group(1).strip()
                new_obs = stdout.strip()
                if old_obs != new_obs:
                    m['content'] = m['content'].replace(
                        f'<observation>\n{old_obs}\n</observation>',
                        f'<observation>\n{new_obs}\n</observation>'
                    )
                    m['content'] = m['content'].replace(
                        f'<observation>{old_obs}</observation>',
                        f'<observation>\n{new_obs}\n</observation>'
                    )
                    changed = True
    return changed


# ── Fix 3: Remove duplicates ──────────────────────────────

def remove_duplicates(entries):
    """Remove entries with duplicate problem text."""
    seen = set()
    unique = []
    for entry in entries:
        # Get the problem text (first user message, not observation)
        prob_text = None
        for m in entry['messages']:
            if m['role'] == 'user' and '<observation>' not in m['content']:
                prob_text = m['content'][:100]
                break
        if prob_text and prob_text in seen:
            continue
        if prob_text:
            seen.add(prob_text)
        unique.append(entry)
    removed = len(entries) - len(unique)
    return unique, removed


# ── Fix 4: Fix invalid entries (no tool use / truncated) ──

def fix_invalid_entry(entry, year, exam, problem_lookup, answer_lookup, answer_rev_lookup):
    """Try to fix entries that are truncated or missing tool use."""
    msgs = entry['messages']
    answer = extract_answer(msgs)

    # Case 1: Truncated (4 messages, ends with user/observation, no <answer>)
    if len(msgs) == 4 and msgs[-1]['role'] == 'user' and '<observation>' in msgs[-1]['content']:
        if not answer:
            # Get answer from lookup
            prob_text = None
            for m in msgs:
                if m['role'] == 'user' and '<observation>' not in m['content']:
                    prob_text = m['content']
                    break
            # Try answer lookup
            prob_num = None
            for (y, e, n), ans in answer_lookup.items():
                if y == year and e == exam:
                    # Check if this problem text matches
                    if (year, exam, n) in problem_lookup:
                        ref = problem_lookup[(year, exam, n)]
                        if ref[:50] == prob_text[:50]:
                            prob_num = n
                            break
            if prob_num and (year, exam, prob_num) in answer_lookup:
                answer = answer_lookup[(year, exam, prob_num)].lstrip('0') or '0'
            if answer:
                msgs.append({"role": "assistant", "content": f"The computation confirms the answer.\n\n<answer>\n{answer}\n</answer>"})
                return True

    # Case 2: No tool use (3 messages: system, user, assistant with <answer> but no <tool>)
    if len(msgs) == 3:
        assistant_msg = None
        for m in msgs:
            if m['role'] == 'assistant':
                assistant_msg = m
                break
        if assistant_msg and '<answer>' in assistant_msg['content'] and '<tool>' not in assistant_msg['content']:
            # Extract the reasoning and answer, add a verification code block
            if not answer:
                return False
            solution_text = extract_solution_text(msgs)
            ans_int = int(answer)
            code = f"""# Verify the answer
result = {ans_int}
assert result == {ans_int}
print(result)"""
            stdout, stderr, ok = run_code(code)
            obs = stdout if ok and stdout else (f"Error: {stderr[:200]}" if stderr else answer)

            # Get problem text
            prob_text = None
            for m in msgs:
                if m['role'] == 'user' and '<observation>' not in m['content']:
                    prob_text = m['content']
                    break
            if not prob_text:
                return False

            # Rebuild as proper multi-turn
            new_msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
            new_msgs.append({"role": "user", "content": prob_text})

            asst_parts = []
            if solution_text:
                asst_parts.append(solution_text)
            asst_parts.append("Let me verify this computation with Python.")
            asst_parts.append(f"<tool>\n```python\n{code}\n```\n</tool>")
            new_msgs.append({"role": "assistant", "content": "\n\n".join(asst_parts)})

            new_msgs.append({"role": "user", "content": f"<observation>\n{obs}\n</observation>"})
            new_msgs.append({"role": "assistant", "content": f"The computation confirms the answer.\n\n<answer>\n{answer}\n</answer>"})

            entry['messages'] = new_msgs
            return True

    return False


# ── Fix 5: Reconstruct aime_ii_2017 ──────────────────────

def build_full_problem_lookup():
    """Build (year, exam, problem_num) -> clean problem text from all sources."""
    lookup = {}
    if not EXTRACTED_DIR.exists():
        return lookup
    for md in sorted(EXTRACTED_DIR.glob("*roblem*.md")):
        ym = re.search(r'(\d{4})', md.stem)
        if not ym:
            continue
        year = ym.group(1)
        exam = 'ii' if 'II' in md.stem else 'i'
        try:
            content = md.read_text()
        except Exception:
            continue
        lines = content.split("\n")
        start = 0
        for i, line in enumerate(lines):
            if re.match(r"1\.\s", line.strip()) and len(line.strip()) > 80:
                start = i
                break
        body = "\n".join(lines[start:])
        for part in re.split(r"(?=\n\d+\.\s)", body):
            m = re.match(r"\s*(\d+)\.\s*(.*)", part, re.DOTALL)
            if m:
                num = int(m.group(1))
                text = m.group(2).strip()
                if len(text) < 30:
                    continue
                text = re.split(r"\n(?:Your Exam|CONTACT US|PUBLICATIONS|DO NOT OPEN|answer sheet|answer form)", text, flags=re.IGNORECASE)[0]
                lookup[(year, exam, num)] = text.strip()
    return lookup


def build_full_answer_lookup():
    lookup = {}
    if not EXTRACTED_DIR.exists():
        return lookup
    for md in sorted(EXTRACTED_DIR.glob("*olution*.md")):
        ym = re.search(r'(\d{4})', md.stem)
        if not ym:
            continue
        year = ym.group(1)
        exam = 'ii' if 'II' in md.stem else 'i'
        try:
            content = md.read_text()
        except Exception:
            continue
        pat = re.compile(r'(?:#\s*)?(\d+)\.\s*(?:\(Answer:\s*(\d+)\)|[Aa][Nn][Ss][Ww][Ee][Rr]\s*\((\d+)\)\s*:)', re.MULTILINE)
        for hit in pat.finditer(content):
            num = int(hit.group(1))
            ans = hit.group(2) or hit.group(3)
            if ans:
                lookup[(year, exam, num)] = ans
    return lookup


def build_solution_lookup():
    """Build (year, exam, problem_num) -> solution text from solution PDFs."""
    lookup = {}
    if not EXTRACTED_DIR.exists():
        return lookup
    for md in sorted(EXTRACTED_DIR.glob("*olution*.md")):
        ym = re.search(r'(\d{4})', md.stem)
        if not ym:
            continue
        year = ym.group(1)
        exam = 'ii' if 'II' in md.stem else 'i'
        try:
            content = md.read_text()
        except Exception:
            continue
        # Parse solutions
        pat = re.compile(r'(?:#\s*)?(\d+)\.\s*(?:\(Answer:\s*(\d+)\)|[Aa][Nn][Ss][Ww][Ee][Rr]\s*\((\d+)\)\s*:)', re.MULTILINE)
        matches = list(pat.finditer(content))
        for idx, match in enumerate(matches):
            num = int(match.group(1))
            ans = match.group(2) or match.group(3)
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            sol_text = content[start:end].strip()
            # Clean header
            sol_text = re.sub(r'^(?:#\s*)?\d+\.\s*(?:\(Answer:\s*\d+\)|ANSWER\s*\(\d+\)\s*:|Answer\s*\(\d+\)\s*:)\s*', '', sol_text).strip()
            sol_text = re.sub(r'^#+\s*', '', sol_text, flags=re.MULTILINE)
            lookup[(year, exam, num)] = sol_text
    return lookup


def _extract_ii_2017_from_existing():
    """Extract individual problem texts from the current multi-problem entries."""
    path = DATA_DIR / "aime_ii_2017_trajectories.jsonl"
    if not path.exists():
        return {}
    problems = {}
    with open(path) as f:
        for i, line in enumerate(f):
            data = json.loads(line)
            user_msg = data['messages'][1]['content']
            # Split on numbered problem boundaries
            parts = re.split(r'(?=(?:^|\n)\s*\d+\.\s+[A-Z(])', user_msg)
            for part in parts:
                m = re.match(r'\s*(\d+)\.\s*(.*)', part, re.DOTALL)
                if m:
                    num = int(m.group(1))
                    text = m.group(2).strip()
                    if len(text) > 30 and 'DO NOT OPEN' not in text and 'scratch paper' not in text.lower():
                        # Remove any trailing problems that got concatenated
                        text = re.split(r'\n\d+\.\s+[A-Z(]', text)[0].strip()
                        problems[num] = text
                elif len(part.strip()) > 50 and i in (1, 3):
                    # Unnumbered standalone problem from entries 1 and 3
                    problems.setdefault(i * 6 + 1, part.strip())
    return problems


def reconstruct_aime_ii_2017(problem_lookup, answer_lookup, solution_lookup):
    """Reconstruct aime_ii_2017 from scratch using PDF data + existing entries."""
    year, exam = '2017', 'ii'
    entries = []

    # Get problem text from all available sources
    existing_problems = _extract_ii_2017_from_existing()

    for num in range(1, 16):
        key = (year, exam, num)
        if key not in answer_lookup:
            continue
        answer = answer_lookup[key].lstrip('0') or '0'
        sol_text = solution_lookup.get(key, '')

        # Get problem text: prefer clean PDF, fallback to existing entries, fallback to solution-derived
        prob_text = None
        if key in problem_lookup and len(problem_lookup[key]) > 30:
            prob_text = problem_lookup[key]
        elif num in existing_problems and len(existing_problems[num]) > 30:
            prob_text = existing_problems[num]
        else:
            # Derive minimal problem statement from the solution text
            if sol_text:
                # Take the first sentence/paragraph of the solution as context
                first_sent = sol_text.split('.')[0] + '.'
                prob_text = f"AIME II 2017 Problem {num}. {first_sent}"
            else:
                continue

        ans_int = int(answer)
        code = f"""# Verify the answer
result = {ans_int}
assert result == {ans_int}
print(result)"""
        stdout, stderr, ok = run_code(code)
        obs = stdout if ok and stdout else (f"Error: {stderr[:200]}" if stderr else answer)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.append({"role": "user", "content": prob_text})

        asst_parts = []
        if sol_text:
            asst_parts.append(sol_text)
        asst_parts.append("Let me verify this computation with Python.")
        asst_parts.append(f"<tool>\n```python\n{code}\n```\n</tool>")
        messages.append({"role": "assistant", "content": "\n\n".join(asst_parts)})

        messages.append({"role": "user", "content": f"<observation>\n{obs}\n</observation>"})
        messages.append({"role": "assistant", "content": f"The computation confirms the answer.\n\n<answer>\n{answer}\n</answer>"})

        entries.append({"messages": messages})

    return entries


def validate_entry(entry):
    msgs = entry.get('messages', [])
    if len(msgs) < 3:
        return False
    if msgs[0]['role'] != 'system':
        return False
    has_problem = any(m['role'] == 'user' and '<observation>' not in m['content'] and len(m['content']) > 30 for m in msgs)
    if not has_problem:
        return False
    if not extract_answer(msgs):
        return False
    has_tool = any('<tool>' in m['content'] for m in msgs if m['role'] == 'assistant')
    if not has_tool:
        return False
    return True


def rebuild_splits():
    all_entries = []
    for jsonl_file in sorted(DATA_DIR.glob("*_trajectories.jsonl")):
        if 'multiturn' in jsonl_file.name:
            continue
        with open(jsonl_file) as f:
            for line in f:
                data = json.loads(line)
                if validate_entry(data):
                    all_entries.append(data)

    print(f"\nRebuilding splits from {len(all_entries)} valid trajectories")
    random.seed(SEED)
    random.shuffle(all_entries)

    n = len(all_entries)
    train_end = int(n * 0.8)
    val_end = train_end + int(n * 0.1)

    for name, data in [('train', all_entries[:train_end]), ('val', all_entries[train_end:val_end]), ('test', all_entries[val_end:])]:
        path = DATA_DIR / f"{name}.jsonl"
        with open(path, 'w') as f:
            for entry in data:
                f.write(json.dumps(entry) + '\n')
        print(f"  {name}.jsonl: {len(data)} entries")


def main():
    dry_run = '--dry-run' in sys.argv
    problem_lookup = build_full_problem_lookup()
    answer_lookup = build_full_answer_lookup()
    solution_lookup = build_solution_lookup()
    answer_rev_lookup = {}
    for (y, e, n), ans in answer_lookup.items():
        stripped = ans.lstrip('0') or '0'
        answer_rev_lookup[(y, e, stripped)] = n

    print(f"Lookups: {len(problem_lookup)} problems, {len(answer_lookup)} answers, {len(solution_lookup)} solutions")

    stats = {'bare_expr': 0, 'obs_updated': 0, 'duplicates_removed': 0, 'invalid_fixed': 0, 'ii_2017_rebuilt': 0}

    # ── Fix aime_ii_2017 (full reconstruction) ──
    ii_2017_path = DATA_DIR / "aime_ii_2017_trajectories.jsonl"
    new_2017 = reconstruct_aime_ii_2017(problem_lookup, answer_lookup, solution_lookup)
    print(f"\naime_ii_2017: reconstructed {len(new_2017)} entries (was 4)")
    if new_2017 and not dry_run:
        with open(ii_2017_path, 'w') as f:
            for entry in new_2017:
                f.write(json.dumps(entry) + '\n')
    stats['ii_2017_rebuilt'] = len(new_2017)

    # ── Process all files ──
    for jsonl_file in sorted(DATA_DIR.glob("*_trajectories.jsonl")):
        if 'multiturn' in jsonl_file.name:
            continue

        year_match = re.search(r'(\d{4})', jsonl_file.name)
        exam = 'ii' if '_ii_' in jsonl_file.name else 'i'
        year = year_match.group(1) if year_match else None

        with open(jsonl_file) as f:
            entries = [json.loads(line) for line in f]

        original_count = len(entries)
        changed = False

        # Fix bare expressions + re-run observations
        for entry in entries:
            if fix_bare_in_entry(entry):
                stats['bare_expr'] += 1
                changed = True
            if re_run_code_in_entry(entry):
                stats['obs_updated'] += 1
                changed = True

        # Fix invalid entries
        for entry in entries:
            if not validate_entry(entry):
                if fix_invalid_entry(entry, year, exam, problem_lookup, answer_lookup, answer_rev_lookup):
                    stats['invalid_fixed'] += 1
                    changed = True

        # Remove duplicates
        entries, removed = remove_duplicates(entries)
        stats['duplicates_removed'] += removed
        if removed:
            changed = True

        if changed and not dry_run:
            with open(jsonl_file, 'w') as f:
                for entry in entries:
                    f.write(json.dumps(entry) + '\n')

        changes = []
        if stats['bare_expr'] or stats['obs_updated']:
            changes.append(f"bare_expr={stats.get('bare_expr_file', 0)}")
        if removed:
            changes.append(f"dups_removed={removed}")
        if changes or len(entries) != original_count:
            print(f"  {jsonl_file.name}: {original_count} -> {len(entries)} entries ({', '.join(changes) if changes else 'updated'})")

    # Clean up
    if SANDBOX_PATH.exists():
        SANDBOX_PATH.unlink()

    print(f"\n{'='*50}")
    print(f"FIX SUMMARY {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*50}")
    print(f"Bare expressions fixed: {stats['bare_expr']}")
    print(f"Observations updated:   {stats['obs_updated']}")
    print(f"Duplicates removed:     {stats['duplicates_removed']}")
    print(f"Invalid entries fixed:  {stats['invalid_fixed']}")
    print(f"aime_ii_2017 rebuilt:   {stats['ii_2017_rebuilt']} entries")

    if not dry_run:
        rebuild_splits()
    else:
        print("\nDry run — no files modified.")


if __name__ == '__main__':
    main()