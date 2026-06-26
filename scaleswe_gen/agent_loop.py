"""
Custom agent loop for ScaleSWE task generation.

Runs an LLM inside a Docker container with bash + submit tools.
Inspired by SWE-agent's approach but self-contained — no framework dependency.

The loop:
  1. Start a Docker container from the given image (or attach to existing)
  2. Send system prompt + user message to the LLM
  3. LLM responds with tool calls (bash, submit)
  4. Execute bash commands inside the container via `docker exec`
  5. Feed output back to the LLM
  6. Repeat until `submit` is called or max_iterations reached
  7. `docker commit` the container to preserve state (optional)
  8. Stop + remove the container (optional)
"""

import json
import subprocess
import time
from typing import Optional

from openai import OpenAI, APIError


def docker_exec(container_id: str, command: str, workdir: str = "/workspace",
                timeout: int = 1800) -> tuple[int, str]:
    """Execute a bash command inside a Docker container.

    Uses `bash -lc` to source the login profile (so conda/pyenv are available).
    Returns (exit_code, combined_output).
    """
    cmd = ["docker", "exec", "-w", workdir, container_id, "bash", "-lc", command]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"[TIMEOUT after {timeout}s]"
    output = result.stdout
    if result.stderr:
        output += "\n[stderr]\n" + result.stderr
    return result.returncode, output


def docker_cp_to_host(container_id: str, src: str, dst: str) -> None:
    """Copy a file from the container to the host."""
    subprocess.run(
        ["docker", "cp", f"{container_id}:{src}", dst],
        check=True, capture_output=True,
    )


def container_exists(name: str) -> bool:
    """Check if a Docker container with the given name exists."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    return name in result.stdout.strip().splitlines()


def docker_remove(name: str) -> None:
    """Stop and remove a container if it exists."""
    if container_exists(name):
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def call_llm_with_retry(client, model, messages, tools, max_tokens=4096,
                        max_retries=3, base_delay=2.0):
    """Call the LLM with exponential backoff on transient failures."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
        except APIError as e:
            last_err = e
            if getattr(e, "status_code", None) in (400, 401, 403, 404):
                raise  # non-retryable
            delay = base_delay * (2 ** attempt)
            print(f"  LLM API error (attempt {attempt+1}/{max_retries}): {e}. Retrying in {delay}s...")
            time.sleep(delay)
        except Exception as e:
            last_err = e
            delay = base_delay * (2 ** attempt)
            print(f"  LLM call failed (attempt {attempt+1}/{max_retries}): {e}. Retrying in {delay}s...")
            time.sleep(delay)
    raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_err}")


def run_agent(
    image: str,
    system_prompt: str,
    llm_config: dict,
    max_iterations: int = 100,
    container_name: Optional[str] = None,
    commit_image: Optional[str] = None,
    use_existing_container: bool = False,
    remove_container_after: bool = True,
    trajectory_path: Optional[str] = None,
) -> dict:
    """
    Run an agentic loop inside a Docker container.

    Args:
        image: Docker image to run. Ignored if use_existing_container=True.
        system_prompt: System prompt for the agent
        llm_config: {"base_url", "api_key", "model"}
        max_iterations: Max LLM turns before giving up
        container_name: Optional name for the container
        commit_image: Optional image tag to commit the container to after completion
        use_existing_container: If True, attach to an already-running container
        remove_container_after: If True, remove the container after completion
        trajectory_path: Optional path to save the full message trajectory as JSONL

    Returns:
        {"container_id", "image", "messages", "iterations", "submitted"}
    """
    name = container_name or f"scaleswe-agent-{int(time.time())}"
    we_started_container = False

    if not use_existing_container:
        if container_exists(name):
            raise RuntimeError(f"Container {name} already exists. Remove it or use a different name.")
        subprocess.run(
            ["docker", "run", "-d", "--name", name, image, "sleep", "infinity"],
            check=True, capture_output=True,
        )
        we_started_container = True
    else:
        if not container_exists(name):
            raise RuntimeError(f"Container {name} does not exist. Cannot attach.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Begin. Follow the plan step by step. Use the bash tool to execute commands. When you are finished, call the submit tool."},
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Execute a bash command inside the container. Output is returned (stdout + stderr, truncated if long).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The bash command to execute"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit",
                "description": "Submit your work and end the session.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    client = OpenAI(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
    )

    submitted = False
    iterations = 0
    traj_file = None
    if trajectory_path:
        traj_file = open(trajectory_path, "w")

    try:
        for i in range(max_iterations):
            iterations = i + 1
            response = call_llm_with_retry(
                client, llm_config["model"], messages, tools
            )
            msg = response.choices[0].message
            msg_dict = msg.model_dump(exclude_none=True)
            messages.append(msg_dict)
            if traj_file:
                traj_file.write(json.dumps({"event": "assistant", "msg": msg_dict}) + "\n")
                traj_file.flush()

            if not msg.tool_calls:
                user_msg = {
                    "role": "user",
                    "content": "Please continue. Use the bash tool to execute commands or call submit to finish.",
                }
                messages.append(user_msg)
                if traj_file:
                    traj_file.write(json.dumps({"event": "user", "msg": user_msg}) + "\n")
                    traj_file.flush()
                continue

            should_break = False
            for tc in msg.tool_calls:
                if tc.function.name == "submit":
                    submitted = True
                    tool_result = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "Submitted. Session ending.",
                    }
                    messages.append(tool_result)
                    if traj_file:
                        traj_file.write(json.dumps({"event": "tool_result", "msg": tool_result}) + "\n")
                        traj_file.flush()
                    should_break = True
                    break
                elif tc.function.name == "bash":
                    try:
                        args = json.loads(tc.function.arguments)
                        cmd = args["command"]
                    except (json.JSONDecodeError, KeyError) as e:
                        tool_result = {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: could not parse bash arguments: {e}. Please send a valid JSON with a 'command' field.",
                        }
                        messages.append(tool_result)
                        if traj_file:
                            traj_file.write(json.dumps({"event": "tool_result", "msg": tool_result}) + "\n")
                            traj_file.flush()
                        continue

                    rc, output = docker_exec(name, cmd)
                    if len(output) > 10000:
                        output = output[:5000] + "\n... [truncated] ...\n" + output[-5000:]
                    tool_result = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"[exit_code={rc}]\n{output}",
                    }
                    messages.append(tool_result)
                    if traj_file:
                        traj_file.write(json.dumps({"event": "tool_result", "msg": tool_result, "command": cmd}) + "\n")
                        traj_file.flush()
                else:
                    tool_result = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"Error: unknown tool '{tc.function.name}'. Available tools: bash, submit.",
                    }
                    messages.append(tool_result)
                    if traj_file:
                        traj_file.write(json.dumps({"event": "tool_result", "msg": tool_result}) + "\n")
                        traj_file.flush()

            if should_break:
                break

    finally:
        committed_image = None
        if commit_image:
            try:
                subprocess.run(
                    ["docker", "commit", name, commit_image],
                    check=True, capture_output=True,
                )
                committed_image = commit_image
            except subprocess.CalledProcessError as e:
                print(f"  Warning: docker commit failed: {e.stderr.decode() if e.stderr else e}")
        # Always stop the container
        subprocess.run(["docker", "stop", name], capture_output=True)
        # Remove if requested
        if remove_container_after and we_started_container:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        if traj_file:
            traj_file.close()

    return {
        "container_id": name,
        "image": committed_image,
        "messages": messages,
        "iterations": iterations,
        "submitted": submitted,
    }
