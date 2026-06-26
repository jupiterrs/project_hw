# Fine-Tune LLM — Agentic Math Solver

Fine-tuning **Llama-3.2-1B-Instruct** to solve AIME-level math problems using an agentic think→code→verify approach, trained via SFT then RL.

## What This Project Does

The goal is to produce a small language model that doesn't just memorize math — it **acts**: it reasons step by step, writes Python code to verify its work, and self-corrects when needed. Think of it as training a mini math agent.

## Current Status

| Step | Status | Description |
|------|--------|-------------|
| 1. Data Engineering | Done | Tokenization, chat templates, data formats |
| 2. Data Extraction | Done | PDF → markdown via MinerU + AoPS scraping |
| 3. SFT Trajectory Generation | In Progress | 528 trajectories (AIME 2001–2018), expanding to 2019–2025 |
| 4. SFT Training | Todo | QLoRA + SFTTrainer on trajectory data |
| 5. RL Phase | Todo | GRPO/DPO with reward = correct answer |
| 6. Inference | Todo | Deploy agent with sandboxed Python execution |

## Data Pipeline

```
AIME PDFs ──► MinerU (PDF→Markdown) ──┐
                                       ├──► Claude Sonnet (Code Generation) ──► SFT Trajectories (JSONL)
AoPS Wiki ──► Scraper (Problem+Answer) ┘
```

### Step 1: Source the problems

**AIME 2001–2018**: Extracted from official competition PDFs via MinerU (VLM-based PDF-to-markdown, run on Colab).

**AIME 2019–2025**: Scraped from Art of Problem Solving wiki using `scrape_aops.py` (with Cloudflare bypass). Answer keys from AoPS + AI-MO/aimo-validation-aime dataset on HuggingFace.

### Step 2: Generate trajectories with verified code

Each problem gets a trajectory where the model:
1. Reads the problem
2. Reasons through the solution
3. Writes Python code to verify the answer
4. Confirms the output matches the known answer

The code generation uses Claude Sonnet 4.5 to write brute-force/computational verification code. Each code block is executed and validated against the known AIME answer. ~75% of problems get real verified code; the remaining (mostly geometry) use stub verification.

### Step 3: Format as JSONL for SFT

Standard chat-completion format used by HuggingFace's SFTTrainer.

## Project Structure

```
fine-tune-llm/
├── sft-data/                        # Training data (JSONL trajectories)
│   ├── aime_i_2001_trajectories.jsonl
│   ├── aime_i_2002_trajectories.jsonl
│   ├── ...                          # 36 files (AIME I & II, 2001–2018)
│   └── aime_ii_2018_trajectories.jsonl
│
├── aime_pdfs/                        # Source data
│   ├── AIMEI2001Problems.pdf         # Competition PDFs (2001–2018)
│   ├── AIMEI2001Solutions.pdf
│   ├── extracted/                    # MinerU markdown output
│   └── ...
│
├── construct_trajectories.py         # Build trajectories from extracted markdown
├── scrape_aops.py                    # Scrape AIME problems from AoPS wiki (2019–2025)
├── generate_new_trajectories.py      # Generate trajectories with brute-force code
├── data-validator.py                 # Validate trajectory quality
├── split_dataset.py                  # Train/test/val splitting
│
├── scripts/archive/                  # Archived scripts from development
│   ├── upgrade_bruteforce.py         # Stub → real code upgrade (v1)
│   ├── upgrade_bruteforce_v2.py      # Upgrade with Sonnet 4.5
│   ├── upgrade_bruteforce_v3.py      # Upgrade with geometry helpers + self-repair
│   ├── fix_*.py                      # Data repair scripts
│   └── ...
│
├── reward/                           # [Future] Reward model for RL phase
├── pyproject.toml
└── README.md
```

## Data Quality

| Metric | Value |
|--------|-------|
| Total trajectories | 528 (2001–2018) + ~180 (2019–2025, in progress) |
| Real verified code | ~71% (code actually computes the answer) |
| Stub code (result = N) | ~29% (mostly geometry — hard to brute-force) |
| All entries have tool/obs/answer tags | 100% |

## Trajectory Format

Each training example teaches the model an agentic loop: **think → code → verify → answer**.

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a math problem solver. Think step by step. Use Python to verify your computations. If you make an error, correct yourself."
    },
    {
      "role": "user",
      "content": "<math problem text>"
    },
    {
      "role": "assistant",
      "content": "<reasoning>\n\nLet me verify this computation with Python.\n\n<tool>\n```python\n<code>\n```\n</tool>"
    },
    {
      "role": "user",
      "content": "<observation>\n<code output>\n</observation>"
    },
    {
      "role": "assistant",
      "content": "The computation confirms the answer.\n\n<answer>\n<final answer>\n</answer>"
    }
  ]
}
```

The `<tool>`/`<observation>` blocks teach the model to use Python as a tool — not just memorize solutions, but actively verify them.

## Why Knowledge Distillation?

Training a 1B-parameter model to solve AIME problems directly is extremely hard. Instead, we:

1. Use a powerful model (Claude Sonnet) to generate high-quality reasoning + code trajectories
2. Fine-tune the small model (Llama-3.2-1B) on these trajectories via SFT
3. Then further improve it with RL (GRPO/DPO), where the reward is whether the answer is correct

This gives the small model a strong starting point — it learns the *form* of agentic reasoning (think, code, verify) from SFT, then RL optimizes for actually getting the right answer.

## Setup

```bash
git clone git@github.com:jupiterrs/fine-tune-llm.git
cd fine-tune-llm
uv sync
export HF_TOKEN="your_token_here"
export ANTHROPIC_API_KEY="your_key_here"  # For trajectory generation
```

## Roadmap

1. **Complete 2019–2025 trajectories** — Finish generating verified code for the new years
2. **Filter & clean dataset** — Remove stub-code entries, create final train/test/val split
3. **Train SFT** — QLoRA fine-tuning on trajectory data (Colab with T4 GPU)
4. **RL phase** — GRPO or DPO training with answer-correctness reward
5. **Inference** — Deploy with sandboxed Python execution for real tool use