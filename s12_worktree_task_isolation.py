#!/usr/bin/env python3
"""
s12: Worktree Task Isolation - Worktree 任务隔离

每个任务独立的 git worktree 目录
"""

import os
import json
import subprocess
from pathlib import Path
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()
WORKTREES_DIR = WORKDIR / ".worktrees"


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not str(path).startswith(str(WORKDIR)):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        return (result.stdout + result.stderr) or "(无输出)"
    except Exception as e:
        return f"Error: {str(e)}"


def run_read(path: str) -> str:
    try:
        return safe_path(path).read_text(encoding="utf-8")[:50000]
    except Exception as e:
        return f"Error: {str(e)}"


def list_worktrees():
    """列出所有 worktree"""
    WORKTREES_DIR.mkdir(exist_ok=True, parents=True)
    index_file = WORKTREES_DIR / "index.json"
    if index_file.exists():
        return json.dumps(json.loads(index_file.read_text()), indent=2)
    return "(无 worktree)"


def create_worktree(name: str, task_id: int):
    """创建 worktree"""
    WORKTREES_DIR.mkdir(exist_ok=True, parents=True)
    branch_name = f"wt/{name}"

    # 更新 index
    index_file = WORKTREES_DIR / "index.json"
    if index_file.exists():
        index = json.loads(index_file.read_text())
    else:
        index = {"worktrees": []}

    index["worktrees"].append({
        "name": name,
        "task_id": task_id,
        "branch": branch_name,
        "status": "active"
    })
    index_file.write_text(json.dumps(index, indent=2))

    return f"Worktree '{name}' created for task {task_id}"


TOOLS = [
    {"name": "bash", "description": "Execute bash",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "create_worktree", "description": "Create worktree for task",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "task_id": {"type": "integer"}}, "required": ["name", "task_id"]}},
    {"name": "list_worktrees", "description": "List all worktrees",
     "input_schema": {"type": "object", "properties": {}}},
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", "")),
    "create_worktree": lambda **kw: create_worktree(kw.get("name", ""), kw.get("task_id", 0)),
    "list_worktrees": lambda **kw: list_worktrees(),
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    while True:
        response = client.messages.create(
            model=MODEL,
            system="You can create worktrees to isolate task execution.",
            messages=messages, tools=TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return response.content[0].text
        results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                handler = TOOL_HANDLERS.get(tool_name)
                output = handler(**block.input) if handler else f"Unknown: {tool_name}"
                print(f"[{tool_name}] {output}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置 ANTHROPIC_API_KEY")
        return
    client = Anthropic(api_key=api_key)
    print("=" * 50)
    print("s12: Worktree Task Isolation")
    print("=" * 50)
    prompt = "Create a worktree named 'auth-feature' for task 1, then list worktrees"
    result = agent_loop(prompt, client)
    print(f"最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()