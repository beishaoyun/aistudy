#!/usr/bin/env python3
"""
s08: Background Tasks - 后台任务

慢操作丢后台，agent 继续想下一步
"""

import os
import uuid
import threading
import subprocess
from pathlib import Path
from collections import deque
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()


class BackgroundManager:
    def __init__(self):
        self.tasks = {}
        self._notification_queue = deque()
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {"status": "running", "command": command, "result": ""}
        thread = threading.Thread(target=self._execute, args=(task_id, command), daemon=True)
        thread.start()
        return f"Background task {task_id} started: {command}"

    def _execute(self, task_id, command):
        try:
            r = subprocess.run(command, shell=True, cwd=str(WORKDIR), capture_output=True, text=True, timeout=300)
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["result"] = output[:500]
        except subprocess.TimeoutExpired:
            self.tasks[task_id]["status"] = "timeout"
            self.tasks[task_id]["result"] = "Error: Timeout (300s)"
        except Exception as e:
            self.tasks[task_id]["status"] = "error"
            self.tasks[task_id]["result"] = f"Error: {str(e)}"
        with self._lock:
            self._notification_queue.append({"task_id": task_id, "result": self.tasks[task_id]["result"]})

    def check(self, task_id: str) -> str:
        task = self.tasks.get(task_id)
        if not task:
            return f"Unknown task: {task_id}"
        return f"Task {task_id}: {task['status']} - {task['result'][:200]}"

    def drain_notifications(self):
        notifs = []
        with self._lock:
            while self._notification_queue:
                notifs.append(self._notification_queue.popleft())
        return notifs


BG = BackgroundManager()


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


def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text(encoding="utf-8")
        return text[:50000] if not limit else "\n".join(text.splitlines()[:limit])
    except Exception as e:
        return f"Error: {str(e)}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"成功写入: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


TOOLS = [
    {"name": "bash", "description": "Execute bash",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "background_run", "description": "Run command in background",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "background_check", "description": "Check background task status",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", "")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "background_run": lambda **kw: BG.run(kw.get("command", "")),
    "background_check": lambda **kw: BG.check(kw.get("task_id", "")),
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    while True:
        notifs = BG.drain_notifications()
        if notifs:
            notif_text = "\n".join(f"[bg:{n['task_id']}] {n['result']}" for n in notifs)
            messages.append({"role": "user", "content": f"<background-results>\n{notif_text}\n</background-results>"})
            messages.append({"role": "assistant", "content": "Noted background results."})

        response = client.messages.create(
            model=MODEL,
            system="You can run tasks in background with background_run.",
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
    print("s08: Background Tasks")
    print("=" * 50)
    prompt = 'Run "sleep 3 && echo done" in the background, then create a file'
    result = agent_loop(prompt, client)
    print(f"最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()