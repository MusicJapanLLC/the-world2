"""
Autonomous code generation loop.

Cycle: read task spec -> generate code -> run tests -> read results -> iterate.
Each agent keeps an independent run history so multiple agents can attack the
same task without overwriting each other's feedback trail.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anthropic

ROOT = Path(__file__).resolve().parents[2]
CODEGEN_DIR = Path(__file__).parent
TASKS_DIR = CODEGEN_DIR / "tasks"
AGENTS_DIR = CODEGEN_DIR / "agents"
RUNS_DIR = CODEGEN_DIR / "runs"


def load_task(task_id: str) -> dict[str, Any]:
    path = TASKS_DIR / f"{task_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Task not found: {path}")
    return json.loads(path.read_text())


def load_agent(agent_id: str) -> dict[str, Any]:
    path = AGENTS_DIR / f"{agent_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Agent not found: {path}")
    agent = json.loads(path.read_text())
    agent.setdefault("id", agent_id)
    agent.setdefault("name", agent_id)
    agent.setdefault("strategy", "Implement the task correctly and efficiently.")
    return agent


def build_prompt(task: dict, agent: dict, history: list[dict]) -> str:
    parts = [
        f"# Agent: {agent['name']} ({agent['id']})",
        f"\n## Agent strategy\n{agent['strategy']}",
        f"\n# Task: {task['name']}",
        f"\n## Goal\n{task['goal']}",
        f"\n## Output file\n`{task['output_file']}`",
        f"\n## Test command\n`{task['test_cmd']}`",
        f"\n## Constraints\n{task.get('constraints', 'None')}",
    ]

    if history:
        parts.append("\n## Previous attempt results (most recent last)")
        for run in history[-3:]:
            parts.append(
                f"\n### Attempt {run['iteration']}"
                f"\n**Code written:**\n```python\n{run['code']}\n```"
                f"\n**Test output:**\n```\n{run['test_output']}\n```"
                f"\n**Passed:** {run['passed']}"
            )
        parts.append(
            "\n## Instructions\n"
            "Study the previous failures carefully. "
            "Follow your agent strategy, fix the observed issues, and produce a stronger attempt. "
            "Output ONLY the raw Python code - no markdown fences, no explanation."
        )
    else:
        parts.append(
            "\n## Instructions\n"
            "Follow your agent strategy and write the implementation. "
            "Output ONLY the raw Python code - no markdown fences, no explanation."
        )

    return "\n".join(parts)


def generate_code(
    task: dict,
    agent: dict,
    history: list[dict],
    client: anthropic.Anthropic,
) -> str:
    prompt = build_prompt(task, agent, history)
    message = client.messages.create(
        model=agent.get("model", "claude-sonnet-4-6"),
        max_tokens=int(agent.get("max_tokens", 4096)),
        messages=[{"role": "user", "content": prompt}],
    )
    code = message.content[0].text.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return code


def run_tests(test_cmd: str, cwd: Path) -> tuple[bool, str]:
    result = subprocess.run(
        test_cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def agent_run_dir(task_id: str, agent_id: str) -> Path:
    return RUNS_DIR / task_id / agent_id


def save_run(
    task_id: str,
    agent: dict,
    iteration: int,
    code: str,
    test_output: str,
    passed: bool,
) -> dict:
    run_dir = agent_run_dir(task_id, agent["id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "task_id": task_id,
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "iteration": iteration,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": passed,
        "code": code,
        "test_output": test_output,
    }
    (run_dir / f"iter_{iteration:03d}.json").write_text(json.dumps(record, indent=2))
    return record


def load_history(task_id: str, agent_id: str) -> list[dict]:
    run_dir = agent_run_dir(task_id, agent_id)
    if not run_dir.exists():
        return []
    records = []
    for file in sorted(run_dir.glob("iter_*.json")):
        records.append(json.loads(file.read_text()))
    return records


def run_loop(task_id: str, max_iterations: int = 10, agent_id: str = "worker-1") -> bool:
    task = load_task(task_id)
    agent = load_agent(agent_id)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    output_path = ROOT / task["output_file"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    history = load_history(task_id, agent_id)
    start_iter = len(history) + 1

    print(
        f"[codegen] agent={agent_id} task={task_id} "
        f"starting at iteration {start_iter}/{max_iterations}"
    )

    for iteration in range(start_iter, max_iterations + 1):
        print(f"\n[codegen:{agent_id}] === Iteration {iteration} ===")

        code = generate_code(task, agent, history, client)
        output_path.write_text(code)
        print(f"[codegen:{agent_id}] wrote {len(code)} chars to {task['output_file']}")

        passed, test_output = run_tests(task["test_cmd"], ROOT)
        print(f"[codegen:{agent_id}] tests {'PASSED' if passed else 'FAILED'}")
        print(test_output[:800])

        record = save_run(task_id, agent, iteration, code, test_output, passed)
        history.append(record)

        if passed:
            print(f"\n[codegen:{agent_id}] SUCCESS at iteration {iteration}")
            return True

        if iteration < max_iterations:
            print(f"[codegen:{agent_id}] retrying with feedback...")

    print(f"\n[codegen:{agent_id}] FAILED after {max_iterations} iterations")
    return False


if __name__ == "__main__":
    task_id = sys.argv[1] if len(sys.argv) > 1 else "example"
    max_iter = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    agent_id = sys.argv[3] if len(sys.argv) > 3 else "worker-1"
    success = run_loop(task_id, max_iter, agent_id)
    sys.exit(0 if success else 1)
