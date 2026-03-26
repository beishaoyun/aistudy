#!/usr/bin/env python3
"""
s09: Agent Teams - 智能体团队

多智能体协作：持久化队友 + 消息通信
"""

import os
import json
import time
import threading
import subprocess
from pathlib import Path
from collections import deque
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()
TEAM_DIR = WORKDIR / ".team"


class TeammateManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.inbox_dir = team_dir / "inbox"
        self.dir.mkdir(exist_ok=True)
        self.inbox_dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}

    def _load_config(self):
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"members": []}

    def _save_config(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def spawn(self, name: str, role: str) -> str:
        member = {"name": name, "role": role, "status": "working"}
        self.config["members"].append(member)
        self._save_config()
        return f"Spawned teammate '{name}' (role: {role})"

    def list_members(self) -> str:
        if not self.config["members"]:
            return "(无队友)"
        return "\n".join(f"- {m['name']}: {m['role']} ({m['status']})" for m in self.config["members"])


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.inbox_dir = inbox_dir

    def send(self, sender: str, to: str, content: str):
        msg = {"from": sender, "to": to, "content": content, "timestamp": time.time()}
        with open(self.inbox_dir / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")

    def read_inbox(self, name: str):
        path = self.inbox_dir / f"{name}.jsonl"
        if not path.exists():
            return []
        msgs = []
        for line in path.read_text().strip().split("\n"):
            if line:
                msgs.append(json.loads(line))
        path.write_text("")
        return msgs


TEAMMATE_MGR = TeammateManager(TEAM_DIR)
MESSAGE_BUS = MessageBus(TEAM_DIR.inbox_dir)


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


TOOLS = [
    {"name": "bash", "description": "Execute bash",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "spawn_teammate", "description": "Spawn a teammate",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}}, "required": ["name", "role"]}},
    {"name": "team_list", "description": "List team members",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send message to teammate",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}}, "required": ["to", "content"]}},
    {"name": "check_inbox", "description": "Check inbox",
     "input_schema": {"type": "object", "properties": {}}},
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", "")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "spawn_teammate": lambda **kw: TEAMMATE_MGR.spawn(kw.get("name", ""), kw.get("role", "")),
    "team_list": lambda **kw: TEAMMATE_MGR.list_members(),
    "send_message": lambda **kw: MESSAGE_BUS.send("user", kw.get("to", ""), kw.get("content", "")),
    "check_inbox": lambda **kw: json.dumps(MESSAGE_BUS.read_inbox("user")),
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    while True:
        response = client.messages.create(
            model=MODEL,
            system="You are a team lead with teammate management capabilities.",
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
    print("s09: Agent Teams")
    print("=" * 50)
    prompt = "Spawn two teammates: alice as coder, bob as reviewer. List the team."
    result = agent_loop(prompt, client)
    print(f"最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()