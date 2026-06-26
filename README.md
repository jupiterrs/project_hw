# project_hw

Distilling a coding agent from a strong teacher model (GLM-5.2-fp8) into a student model (Qwen2.5-Coder-7B-Instruct) via rejection fine-tuning (RFT) on the ScaleSWE dataset. The approach follows the [ScaleSWE paper](https://arxiv.org/abs/2506.11835): generate trajectories on real GitHub bug-fix tasks, keep only those that pass tests, and fine-tune the student on the filtered set.

## Pipeline

1. **Trajectory generation** — Run the teacher model on ScaleSWE task instances using [AweAgent](https://github.com/AweAI-Team/AweAgent). Each instance is a real GitHub bug-fix PR with passing/failing tests.
2. **Rejection filtering** — Keep only trajectories where the agent's patch passes all `FAIL_TO_PASS` and `PASS_TO_PASS` tests.
3. **SFT format conversion** — Convert successful trajectories to OpenAI messages format for LlamaFactory.
4. **Fine-tuning** — Train Qwen2.5-Coder-7B-Instruct with LoRA.
5. **Evaluation** — Run the merged model on SWE-bench Verified.

## What is AweAgent?

[AweAgent](https://github.com/AweAI-Team/AweAgent) is an open-source agent framework purpose-built for SWE-bench-style tasks. It handles:

- **Docker container lifecycle** — spins up a container per task instance with the repo checked out at the correct commit, test patch applied, and dependencies installed.
- **Tool execution** — gives the LLM agent tools for bash, file viewing, and file editing inside the container.
- **Trajectory logging** — records every LLM call, tool call, and tool result as a JSONL trajectory for later SFT conversion and analysis.
- **Evaluation harness** — runs the FAIL_TO_PASS and PASS_TO_PASS tests against the agent's patch to determine success.

We use AweAgent instead of the upstream SWE-agent harness because it supports Anthropic-compatible API endpoints (via a proxy) and has better support for the ScaleSWE task instance format.

## Repo layout

```
configs/              # LLM and task configs (GLM-5.2, ScaleSWE, vLLM serving)
scripts/              # Batch runner, throughput analysis, SFT conversion, image filter
scaleswe-pipeline/    # Pipeline orchestration code
fine-tune-llm/        # Training configs and helpers
setup_gpu_server.sh   # One-shot GPU server provisioning script
pyproject.toml        # Python project definition
uv.lock               # Locked dependencies
```

## Key scripts

- `scripts/auto_concurrent.sh` — Batch runner with time-based concurrency (4 day / 8 night), chunked execution (16–32 instances per batch), Docker cleanup between cycles, and auto-resume from completed instances by scanning all prior trajectory outputs.
- `scripts/filter_available_images.py` — Pre-checks which `aweaiteam/scaleswe:<instance_id>` Docker images exist on Docker Hub (via `docker manifest inspect`, 8-way parallel) and writes a filtered JSONL. Avoids wasting 3 retries per missing image across ~5,000 instances.
- `scripts/success_rate.py` — Aggregates success rate across all run subdirs, deduped by `instance_id`. Handles malformed trajectory lines without crashing.
- `scripts/throughput.py` — Analyzes trajectory generation throughput (durations, token counts, success/fail breakdowns) and estimates wall-clock time to reach a target number of successful trajectories.
- `scripts/swesmith_to_sft.py` — Converts SWE-smith parquet trajectory files to LlamaFactory-compatible JSONL format.
- `setup_gpu_server.sh` — One-shot provisioning for the GPU server: Docker install, CUDA compatibility libraries, env vars, disk layout for `/tmp-tini`.

## Status

| Metric | Value |
|---|---|
| Total ScaleSWE instances | 20,181 |
| Instances processed | 3,212 |
| Successful trajectories | 1,674 |
| Success rate | 52.1% |
| Target | ~7,000 successful trajectories |
| Training data (current, placeholder) | 2,000 samples (Scale-SWE-Distilled) |
| Student model | Qwen2.5-Coder-7B-Instruct |
| Teacher model | GLM-5.2-fp8 |
| Hardware | 8× H200 GPUs |

## Infrastructure & environment

### GPU server setup

- 8× H200 GPUs on a shared lab machine.
- Python environment managed with [`uv`](https://github.com/astral-sh/uv). Reproduce with `uv sync`.
- `setup_gpu_server.sh` provisions Docker, CUDA compatibility libraries, and the disk layout described below.

### Docker data-root on local NVMe

The `/public` filesystem is NFS-mounted, which is incompatible with Docker's `overlay2` storage driver. We moved the Docker data-root to `/tmp-tini` (local NVMe, ext4):

```bash
# /etc/docker/daemon.json
{
  "data-root": "/tmp-tini/docker"
}
```

This eliminated container creation timeouts (60s with `vfs` on NFS → instant with `overlay2` on ext4).

### Environment variables

To avoid filling `/home` (which has a small quota) with caches:

```bash
export HF_HOME=/public/lianghong/nurdaulet_absattarov/.cache/huggingface
export UV_CACHE_DIR=/public/lianghong/nurdaulet_absattarov/.cache/uv
export PIP_CACHE_DIR=/public/lianghong/nurdaulet_absattarov/.cache/pip
```

For Docker, `TMPDIR` must NOT be set to an NFS path — it breaks PTY socket creation. We keep Docker invocations running with the default `TMPDIR`.

## Challenges & solutions

| Challenge | Solution |
|---|---|
| Docker overlayfs incompatible with NFS (`/public`) | Moved Docker data-root to `/tmp-tini` (local NVMe, ext4) |
| `TMPDIR` on NFS broke Docker PTY sockets | Removed `TMPDIR` override for Docker commands |
| Server crashes from `/home` filling with HuggingFace cache | Set `HF_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR` to `/public` |
| ~5,000 ScaleSWE instances had no published Docker image | Wrote `filter_available_images.py` to pre-check image availability |
| Docker container creation timeout (60s) with `vfs` storage driver | Switched to `overlay2` on `/tmp-tini` (ext4 filesystem) |
| SWE-smith `gather.py` bug: reads `PASS_TO_FAIL` instead of `FAIL_TO_PASS` | Patched report files to copy `FAIL_TO_PASS` → `PASS_TO_FAIL` |

## Training configuration

- **Base model:** Qwen2.5-Coder-7B-Instruct
- **Method:** LoRA (rank 8, alpha 16, all linear layers)
- **Hyperparameters:** 3 epochs, learning rate 1e-5, cosine schedule, 10% warmup, BF16
- **Hardware:** 8× H200 GPUs
- **Framework:** LlamaFactory
- **Max sequence length:** 32,768 tokens
- **Effective batch size:** 8 (per_device_train_batch_size=1 × gradient_accumulation_steps=8)

Configured but not yet run with self-generated trajectory data. Currently using 2,000 samples from Scale-SWE-Distilled as placeholder.

## SWE-smith task instance generation

Studied how [SWE-smith](https://github.com/SWE-agent/SWE-smith) constructs task instances from GitHub PRs:

1. Clone the repo at the base commit (before the PR).
2. Apply the test patch (modifications to test files only).
3. Run the test suite to determine which tests transition from PASS→FAIL (FAIL_TO_PASS) and which remain PASS (PASS_TO_PASS).
4. Package the environment (repo + deps + test patch) as a Docker image tagged `aweaiteam/scaleswe:<instance_id>`.

This informs how we might extend the dataset with additional repos or filter for training-relevant instances.

## Next steps

1. **Finish trajectory generation** — Continue running until ~7,000 successful trajectories collected (currently at 1,674, ~24% complete).
2. **Convert self-generated trajectories to SFT format** — Run conversion on the 1,674 successful trajectories.
3. **Train Qwen2.5-Coder-7B-Instruct** on self-generated data (replace the current 2,000 distilled samples).
5. **Evaluate on SWE-bench Verified** — Run the merged model on 500 instances using AweAgent + SWE-bench harness.
6. **Compare** against baseline Qwen2.5-Coder-7B-Instruct and SWE-smith's result.

## Literature review

- [SWE-gym](https://arxiv.org/abs/2412.21139) — training environment for SWE agents.
- [SWE-smith](https://arxiv.org/abs/2412.21147) — scalable task instance generation from GitHub PRs.
- [ScaleSWE](https://arxiv.org/abs/2506.11835) — rejection fine-tuning recipe for coding agents.
- [SWE-agent](https://arxiv.org/abs/2405.15793) — agent framework for SWE-bench.
- Rejection Fine-Tuning (RFT) — methodology for filtering successful trajectories before SFT.

## Upstream repos (not included in this repo)

- [AweAgent](https://github.com/AweAI-Team/AweAgent) — agent framework.
- [LlamaFactory](https://github.com/hiyouga/LlamaFactory) — training framework.
- [SWE-smith](https://github.com/SWE-agent/SWE-smith) — task instance generation.
