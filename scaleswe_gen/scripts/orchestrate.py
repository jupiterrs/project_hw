"""
ScaleSWE multi-agent orchestrator.

Pipeline for one (repo, pr) pair:
  1. EBA  -> builds Docker image with repo + deps installed
  2. UCA  -> writes fail_to_pass.py inside that image
  3. PSWA -> writes the problem statement

Each agent runs via the custom agent_loop inside a Docker container.
Outputs are collected and passed forward as inputs to the next agent.

Usage:
    python scripts/orchestrate.py \
        --repo psf/requests \
        --commit <merge_commit_sha> \
        --pr-title "..." \
        --pr-description "..." \
        --commit-message "..." \
        --base-image scaleswe-base:latest \
        --llm-config configs/llm/glm52_api.yaml \
        --output-dir /tmp/scaleswe_out
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from string import Template

# Allow running as a script from the repo root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_loop import run_agent, docker_exec, docker_cp_to_host, docker_remove  # noqa: E402

PROMPTS_DIR = PROJECT_ROOT / "prompts"


def load_llm_config(path: str) -> dict:
    import yaml
    with open(path) as f:
        cfg = yaml.safe_load(f)
    api_key = cfg.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    if not api_key:
        api_key = os.environ.get("GLM_API_KEY", "dummy")
    return {
        "base_url": cfg["base_url"],
        "api_key": api_key,
        "model": cfg["model"],
    }


def render_prompt(template_path: Path, **vars) -> str:
    with open(template_path) as f:
        return Template(f.read()).safe_substitute(**vars)


def repo_name_from_url(repo_url: str) -> str:
    return repo_url.rsplit("/", 1)[-1].replace(".git", "")


def clone_repo_in_container(container_name: str, repo_url: str, commit: str) -> None:
    """Clone the repo at the given commit inside a running container.

    Tries plain checkout first. If the SHA isn't in the cloned history
    (common for PR commits on forks/branches), fetches PR refs and retries.
    """
    repo_name = repo_name_from_url(repo_url)

    # 1. Full clone (no --depth, no --single-branch)
    rc, out = docker_exec(container_name, f"git clone {repo_url} /workspace/{repo_name}", workdir="/workspace")
    if rc != 0:
        raise RuntimeError(f"git clone failed:\n{out}")

    # 2. Try checkout
    rc, out = docker_exec(
        container_name,
        f"cd /workspace/{repo_name} && git checkout {commit}",
        workdir="/workspace",
    )
    if rc == 0:
        return

    # 3. Checkout failed — fetch PR refs (refs/pull/*) and all tags
    print(f"  Checkout failed, fetching PR refs and tags...")
    rc, out = docker_exec(
        container_name,
        f"cd /workspace/{repo_name} && git config remote.origin.fetch '+refs/pull/*:refs/pull/*' && git fetch --all --tags",
        workdir="/workspace",
    )
    if rc != 0:
        raise RuntimeError(f"git fetch failed:\n{out}")

    # 4. Retry checkout
    rc, out = docker_exec(
        container_name,
        f"cd /workspace/{repo_name} && git checkout {commit}",
        workdir="/workspace",
    )
    if rc != 0:
        raise RuntimeError(
            f"Could not check out commit {commit} in {repo_name}.\n"
            f"Verify the SHA exists in the repo. Last output:\n{out}"
        )


def extract_file_from_container(container_name: str, src: str, dst: str) -> bool:
    """Copy a file from the container to the host. Returns True if successful."""
    try:
        docker_cp_to_host(container_name, src, dst)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Warning: could not extract {src}: {e.stderr.decode() if e.stderr else e}")
        return False


def run_eba(repo_url: str, commit: str, base_image: str, llm_config: dict,
            output_dir: Path, max_iterations: int = 100) -> dict:
    """EBA: clone repo, install deps, return committed image tag."""
    repo_name = repo_name_from_url(repo_url)
    prompt = render_prompt(PROMPTS_DIR / "eba.md", repository=repo_name)

    container_name = f"eba-{repo_name}-{commit[:8]}-{int(time.time())}"
    new_image = f"scaleswe-env:{repo_name}-{commit[:8]}"
    traj_path = str(output_dir / "eba_trajectory.jsonl")

    # Start container from base image
    subprocess.run(
        ["docker", "run", "-d", "--name", container_name, base_image, "sleep", "infinity"],
        check=True, capture_output=True,
    )
    try:
        clone_repo_in_container(container_name, repo_url, commit)
    except RuntimeError as e:
        docker_remove(container_name)
        raise

    system_with_context = prompt + (
        f"\n\nThe repository has been cloned to /workspace/{repo_name} at commit {commit}. "
        "Begin setup."
    )

    try:
        result = run_agent(
            image=base_image,  # ignored since use_existing_container=True
            system_prompt=system_with_context,
            llm_config=llm_config,
            max_iterations=max_iterations,
            container_name=container_name,
            commit_image=new_image,
            use_existing_container=True,
            remove_container_after=False,  # keep for inspection; commit already snapshot
            trajectory_path=traj_path,
        )
    except Exception:
        docker_remove(container_name)
        raise

    return {
        "image": new_image,
        "repo_name": repo_name,
        "container_id": container_name,
        "iterations": result["iterations"],
        "submitted": result["submitted"],
        "trajectory": traj_path,
    }


def run_uca(env_image: str, repo_name: str, commit: str, pr_title: str,
            pr_description: str, commit_message: str,
            problem_statement: str, llm_config: dict,
            output_dir: Path, max_iterations: int = 100) -> dict:
    """UCA: write fail_to_pass.py inside the EBA-built image."""
    prompt = render_prompt(
        PROMPTS_DIR / "uca.md",
        repository=repo_name,
        commit_id=commit,
        problem_statement=problem_statement,
        pr_description=pr_description,
        commit_message=commit_message,
    )

    container_name = f"uca-{repo_name}-{commit[:8]}-{int(time.time())}"
    test_file_host = output_dir / "fail_to_pass.py"
    traj_path = str(output_dir / "uca_trajectory.jsonl")

    result = run_agent(
        image=env_image,
        system_prompt=prompt,
        llm_config=llm_config,
        max_iterations=max_iterations,
        container_name=container_name,
        commit_image=None,
        remove_container_after=False,  # keep for debugging
        trajectory_path=traj_path,
    )

    extracted = extract_file_from_container(
        container_name,
        f"/workspace/{repo_name}/fail_to_pass.py",
        str(test_file_host),
    )

    test_file_content = None
    if extracted and test_file_host.exists():
        test_file_content = test_file_host.read_text()

    return {
        "test_file": str(test_file_host) if test_file_host.exists() else None,
        "test_file_content": test_file_content,
        "container_id": container_name,
        "iterations": result["iterations"],
        "submitted": result["submitted"],
        "trajectory": traj_path,
    }


def run_pswa(env_image: str, repo_name: str, commit: str, pr_title: str,
             pr_description: str, commit_message: str,
             f2p_tests: str, llm_config: dict,
             output_dir: Path, max_iterations: int = 50) -> dict:
    """PSWA: write problem statement."""
    prompt = render_prompt(
        PROMPTS_DIR / "pswa.md",
        repository=repo_name,
        commit_id=commit,
        pr_description=pr_description,
        commit_message=commit_message,
        f2p=f2p_tests,
    )

    container_name = f"pswa-{repo_name}-{commit[:8]}-{int(time.time())}"
    issue_host = output_dir / "issue_draft.txt"
    traj_path = str(output_dir / "pswa_trajectory.jsonl")

    result = run_agent(
        image=env_image,
        system_prompt=prompt,
        llm_config=llm_config,
        max_iterations=max_iterations,
        container_name=container_name,
        commit_image=None,
        remove_container_after=False,
        trajectory_path=traj_path,
    )

    extracted = extract_file_from_container(
        container_name,
        "/workspace/issue_draft.txt",
        str(issue_host),
    )

    issue_content = None
    if extracted and issue_host.exists():
        issue_content = issue_host.read_text()

    return {
        "problem_statement": issue_content,
        "issue_file": str(issue_host) if issue_host.exists() else None,
        "container_id": container_name,
        "iterations": result["iterations"],
        "submitted": result["submitted"],
        "trajectory": traj_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub repo URL or owner/name")
    parser.add_argument("--commit", required=True, help="Merge commit SHA")
    parser.add_argument("--pr-title", default="")
    parser.add_argument("--pr-description", default="")
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--base-image", default="scaleswe-base:latest")
    parser.add_argument("--llm-config", default=str(PROJECT_ROOT / "configs/llm/glm52_api.yaml"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--only", choices=["eba", "uca", "pswa"], action="append",
                        help="Run only the specified agent(s). Can be repeated. Default: all three.")
    parser.add_argument("--env-image", default=None,
                        help="Pre-built EBA image (required with --only uca/pswa).")
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    llm_config = load_llm_config(args.llm_config)
    repo_url = args.repo if args.repo.startswith("http") else f"https://github.com/{args.repo}.git"
    only = args.only or ["eba", "uca", "pswa"]

    eba_result = uca_result = pswa_result = None

    if "eba" in only:
        print(f"[EBA] Running on {args.repo}@{args.commit[:8]}...")
        eba_result = run_eba(repo_url, args.commit, args.base_image, llm_config,
                             output_dir=out, max_iterations=args.max_iterations)
        print(f"  EBA done. Image: {eba_result['image']}, submitted: {eba_result['submitted']}, iters: {eba_result['iterations']}")
    elif "uca" in only or "pswa" in only:
        if not args.env_image:
            print("ERROR: --env-image required when running UCA/PSWA without EBA")
            sys.exit(1)
        eba_result = {"image": args.env_image, "repo_name": repo_name_from_url(repo_url),
                      "iterations": 0, "submitted": True}

    if "uca" in only:
        print(f"[UCA] Running...")
        uca_result = run_uca(
            eba_result["image"], eba_result["repo_name"], args.commit,
            args.pr_title, args.pr_description, args.commit_message,
            problem_statement="",
            llm_config=llm_config,
            output_dir=out,
            max_iterations=args.max_iterations,
        )
        print(f"  UCA done. Test file: {uca_result['test_file']}, submitted: {uca_result['submitted']}, iters: {uca_result['iterations']}")

    if "pswa" in only:
        print(f"[PSWA] Running...")
        pswa_result = run_pswa(
            eba_result["image"], eba_result["repo_name"], args.commit,
            args.pr_title, args.pr_description, args.commit_message,
            f2p_tests=uca_result.get("test_file_content") if uca_result else "",
            llm_config=llm_config,
            output_dir=out,
            max_iterations=min(args.max_iterations, 50),
        )
        print(f"  PSWA done. Issue: {pswa_result['issue_file']}, submitted: {pswa_result['submitted']}, iters: {pswa_result['iterations']}")

    result = {
        "repo": args.repo,
        "commit": args.commit,
        "env_image": eba_result["image"] if eba_result else None,
        "test_file": uca_result["test_file"] if uca_result else None,
        "problem_statement_file": pswa_result["issue_file"] if pswa_result else None,
        "eba_iterations": eba_result["iterations"] if eba_result else None,
        "uca_iterations": uca_result["iterations"] if uca_result else None,
        "pswa_iterations": pswa_result["iterations"] if pswa_result else None,
        "eba_submitted": eba_result["submitted"] if eba_result else None,
        "uca_submitted": uca_result["submitted"] if uca_result else None,
        "pswa_submitted": pswa_result["submitted"] if pswa_result else None,
    }
    with open(out / "result.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nDone. Result: {out / 'result.json'}")


if __name__ == "__main__":
    main()
