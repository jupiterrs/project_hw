# scaleswe_gen

Implementation of the ScaleSWE multi-agent framework for generating SWE-bench-style task instances from GitHub PRs. Three specialized agents (EBA, UCA, PSWA) run inside Docker containers to produce executable environments, test suites, and problem statements.

Based on the [ScaleSWE paper](https://arxiv.org/abs/2506.11835). Prompts are transcribed from Appendix E.

## Pipeline

For each (repo, PR) pair:

1. **EBA (Environment Builder Agent)** — Clones the repo inside a base Ubuntu+Miniconda container, installs dependencies, runs tests until they pass, then `docker commit`s the result as the environment image.
2. **UCA (Unit-test Creator Agent)** — Runs inside the EBA-built image, analyzes the PR diff, writes `fail_to_pass.py` with 2–10 tests, and verifies them via time-travel (`git checkout commit^1` → tests fail, `git checkout commit` → tests pass).
3. **PSWA (Problem Statement Writer Agent)** — Runs inside the EBA-built image, reads the diff + F2P tests, drafts a GitHub-issue-style problem statement without leaking the solution.

## Directory layout

```
scaleswe_gen/
├── prompts/
│   ├── eba.md                  # EBA system prompt (from paper Appendix E)
│   ├── uca.md                  # UCA system prompt
│   └── pswa.md                 # PSWA system prompt
├── base_image/
│   └── Dockerfile              # Ubuntu 22.04 + Miniconda + build-essential + git
├── configs/
│   └── llm/
│       └── glm52_api.yaml      # LLM endpoint config (vLLM serving GLM-5.2-fp8)
├── scripts/
│   ├── orchestrate.py          # EBA → UCA → PSWA pipeline
│   ├── setup.sh                # One-shot setup: venv + deps + base image
│   └── build_base_image.sh     # Build the base Docker image
├── agent_loop.py               # Custom agentic loop (bash + submit tools)
├── requirements.txt            # Python deps (openai, pyyaml, docker)
└── README.md
```

## Setup

```bash
# 1. Clone this repo on the CPU server
git clone git@github.com:jupiterrs/project_hw.git
cd project_hw/scaleswe_gen   # or wherever you place this dir

# 2. Run setup
bash scripts/setup.sh

# 3. Set API key (if your vLLM proxy requires one)
export GLM_API_KEY=your-key-here

# 4. Start vLLM serving GLM-5.2-fp8 on localhost:8080
#    (separate terminal — your existing vLLM serve command)
```

## Usage

```bash
python scripts/orchestrate.py \
    --repo psf/requests \
    --commit <merge_commit_sha> \
    --pr-title "Fix header parsing" \
    --pr-description "..." \
    --commit-message "..." \
    --base-image scaleswe-base:latest \
    --llm-config configs/llm/glm52_api.yaml \
    --output-dir /tmp/scaleswe_out/psf-requests-<sha>
```

Outputs in `--output-dir`:
- `fail_to_pass.py` — UCA's test file
- `issue_draft.txt` — PSWA's problem statement
- `result.json` — metadata (env image tag, iterations, etc.)

The EBA-built Docker image is tagged `scaleswe-env:<repo>-<commit>` and can be reused for multiple PRs on the same repo (the paper samples at most 10 PRs per env).

## How the agent loop works

`agent_loop.py` implements a minimal SWE-agent-style loop:

1. `docker run -d <image> sleep infinity` — start a persistent container (or attach to an existing one via `use_existing_container=True`)
2. Send system prompt + user message to the LLM (via OpenAI-compatible API)
3. LLM responds with tool calls: `bash` or `submit`
4. `bash` calls execute via `docker exec -w /workdir <container> bash -lc "<command>"`
5. Output (stdout + stderr, truncated to 10k chars) is fed back as a tool result
6. Loop until `submit` is called or `max_iterations` reached
7. `docker commit <container> <tag>` preserves state for the next agent

No SWE-agent framework dependency — just `openai` + `docker`.

## LLM serving

The agent loop calls an OpenAI-compatible API. We use GLM-5.2-fp8 served via an Anthropic-compatible proxy on a separate GPU server. Point `configs/llm/glm52_api.yaml` at your proxy endpoint:

```yaml
base_url: http://your-proxy-host:port/v1
api_key: $GLM_API_KEY                # env var reference, or literal
model: glm-5.2-fp8
```

Set the API key before running:
```bash
export GLM_API_KEY=your-key-here
```

No vLLM or local model serving required on the CPU server — just network access to the proxy.

## EBA flow

The paper's EBA prompt assumes the repo is **already cloned** at `/workspace/<repository>` before the agent starts. The orchestrator handles this:

1. `docker run -d scaleswe-base:latest sleep infinity` — start base container
2. `docker exec ... git clone <repo_url> /workspace/<repo_name>` — clone repo
3. `docker exec ... git checkout <commit>` — check out the merge commit
4. Hand off to EBA agent: runs inside the same container, installs deps, runs tests
5. `docker commit <container> scaleswe-env:<repo>-<commit>` — freeze state

EBA only does dependency installation + test running. It does NOT clone the repo.

## Notes

- **EBA reuses across PRs:** Once EBA builds `scaleswe-env:<repo>-<commit>`, UCA and PSWA can run against it for multiple PRs on the same repo. The orchestrator currently rebuilds per PR; a future improvement is to cache env images by repo.
- **Cost/time:** Each agent may take 10–100 LLM iterations depending on repo complexity. Budget ~$0.50–$5 per (repo, PR) pair at typical API prices.
- **Failure modes:** If an agent doesn't call `submit` within `max_iterations`, the container is still committed (partial progress) and `submitted: false` is recorded in `result.json`.

## Caveats vs the paper

- The paper uses **SWE-agent** as the framework and **DeepSeek v3.1/v3.2** as the LLM (Gemini3-Pro for PSWA). This implementation uses a custom loop and **GLM-5.2-fp8** for all three.
- The paper's prompts have been transcribed verbatim from Appendix E; no modifications.
- PSWA in the paper uses Gemini3-Pro because it produces more rigorous problem statements. With GLM-5.2-fp8, expect somewhat lower quality.
