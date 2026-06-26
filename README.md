# project_hw

Distilling a coding agent from a strong teacher model (GLM-5.2-fp8) into a student model (Qwen2.5-Coder-7B-Instruct) via rejection fine-tuning (RFT) on the ScaleSWE dataset.

## Pipeline

1. **Trajectory generation** — Run the teacher model on ScaleSWE task instances using [AweAgent](https://github.com/AweAI-Team/AweAgent). Each instance is a real GitHub bug-fix PR with passing/failing tests.
2. **Rejection filtering** — Keep only trajectories where the agent's patch passes all `FAIL_TO_PASS` and `PASS_TO_PASS` tests.
3. **SFT format conversion** — Convert successful trajectories to OpenAI messages format for LlamaFactory.
4. **Fine-tuning** — Train Qwen2.5-Coder-7B-Instruct with LoRA.
5. **Evaluation** — Run the merged model on SWE-bench Verified.

## Repo layout

```
configs/              # LLM and task configs (GLM-5.2, ScaleSWE, vLLM serving)
scripts/              # Batch runner, throughput analysis, SFT conversion
scaleswe-pipeline/    # Pipeline orchestration code
fine-tune-llm/        # Training configs and helpers
setup_gpu_server.sh   # One-shot GPU server provisioning script
pyproject.toml        # Python project definition
uv.lock               # Locked dependencies
```

## Key scripts

- `scripts/auto_concurrent.sh` — Batch runner with time-based concurrency (4 day / 8 night), chunked execution, Docker cleanup between cycles, auto-resume from completed instances.
- `scripts/filter_available_images.py` — Pre-checks which `aweaiteam/scaleswe:<instance_id>` Docker images exist on Docker Hub before launching jobs.
- `scripts/success_rate.py` — Aggregates success rate across all run subdirs, deduped by `instance_id`.
- `scripts/throughput.py` — Analyzes trajectory generation throughput and estimates wall-clock time to target.

## Status

| Metric | Value |
|---|---|
| Instances processed | 3,212 |
| Successful trajectories | 1,674 |
| Success rate | 52.1% |
| Target | ~7,000 successful trajectories |
| Training data | 2,000 samples (Scale-SWE-Distilled, placeholder) |
| Student model | Qwen2.5-Coder-7B-Instruct |
| Teacher model | GLM-5.2-fp8 |
| Hardware | 8× H200 GPUs |

## Upstream repos (not included)

- [AweAgent](https://github.com/AweAI-Team/AweAgent) — agent framework
- [LlamaFactory](https://github.com/hiyouga/LlamaFactory) — training framework
- [SWE-smith](https://github.com/SWE-agent/SWE-smith) — task instance generation

## Environment

Python deps managed with [`uv`](https://github.com/astral-sh/uv). Reproduce with:
```bash
uv sync
```

Requires Docker, 8× H200 GPUs (or equivalent), and access to GLM-5.2-fp8 via an Anthropic-compatible proxy.
