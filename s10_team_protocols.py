#!/usr/bin/env python3
"""
s10: Team Protocols - 团队协议

结构化协调：shutdown + plan approval 协议
"""

import os
import json
import time
import uuid
import subprocess
from pathlib import Path
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()

# 协议状态
shutdown_requests = {}
plan_requests = {}


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


TOOLS = [
    {"name": "bash", "description": "Execute bash",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "shutdown_request", "description": "Request teammate shutdown",
     "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "plan_approval", "description": "Request plan approval",
     "input_schema": {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]}},
    {"name": "check_requests", "description": "Check pending requests",
     "input_schema": {"type": "object", "properties": {}}},
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", "")),
    "shutdown_request": lambda **kw: f"Shutdown request sent to {kw.get('teammate')}",
    "plan_approval": lambda **kw: f"Plan approval requested: {kw.get('plan')[:50]}...",
    "check_requests": lambda **kw: f"Pending: {len(shutdown_requests)} shutdown, {len(plan_requests)} plan",
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    while True:
        response = client.messages.create(
            model=MODEL,
            system="You can request shutdown or plan approval from teammates.",
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
    print("s10: Team Protocols")
    print("=" * 50)
    prompt = "Check pending requests"
    result = agent_loop(prompt, client)
    print(f"最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()