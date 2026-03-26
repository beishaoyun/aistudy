#!/usr/bin/env python3
"""
s11: Autonomous Agents - 自治智能体

队友自己看任务板，有活就认领
"""

import os
import json
import time
import subprocess
from pathlib import Path
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()
TASKS_DIR = WORKDIR / ".tasks"


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


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"成功: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def scan_unclaimed_tasks():
    """扫描未认领的任务"""
    TASKS_DIR.mkdir(exist_ok=True)
    tasks = []
    for f in TASKS_DIR.glob("task_*.json"):
        try:
            task = json.loads(f.read_text())
            if task.get("status") == "pending" and not task.get("owner"):
                tasks.append(task)
        except:
            pass
    return tasks


TOOLS = [
    {"name": "bash", "description": "Execute bash",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "scan_tasks", "description": "Scan unclaimed tasks",
     "input_schema": {"type": "object", "properties": {}}},
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", "")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "scan_tasks": lambda **kw: json.dumps(scan_unclaimed_tasks()),
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    while True:
        response = client.messages.create(
            model=MODEL,
            system="You are an autonomous agent. Scan tasks and claim unclaimed ones.",
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
                print(f"[{tool_name}] {output[:200]}...")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置 ANTHROPIC_API_KEY")
        return
    client = Anthropic(api_key=api_key)
    print("=" * 50)
    print("s11: Autonomous Agents")
    print("=" * 50)
    prompt = "Scan unclaimed tasks"
    result = agent_loop(prompt, client)
    print(f"最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()