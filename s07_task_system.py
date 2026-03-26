# s07: Task System (任务系统)

`s01 > s02 > s03 > s04 > s05 > s06 | [ s07 ] s08 > s09 > s10 > s11 > s12`

> *"大目标要拆成小任务, 排好序, 记在磁盘上"* -- 文件持久化的任务图, 为多 agent 协作打基础。
>
> **Harness 层**: 持久化任务 -- 比任何一次对话都长命的目标。

## 问题

s03 的 TodoManager 只是内存中的扁平清单: 没有顺序、没有依赖、状态只有做完没做完。真实目标是有结构的 -- 任务 B 依赖任务 A, 任务 C 和 D 可以并行, 任务 E 要等 C 和 D 都完成。

## 解决方案

把扁平清单升级为持久化到磁盘的**任务图**。每个任务是一个 JSON 文件, 有状态、前置依赖 (`blockedBy`) 和后置依赖 (`blocks`)。

```
.tasks/
  task_1.json  {"id":1, "status":"completed"}
  task_2.json  {"id":2, "blockedBy":[1], "status":"pending"}
  task_3.json  {"id":3, "blockedBy":[1], "status":"pending"}
  task_4.json  {"id":4, "blockedBy":[2,3], "status":"pending"}

任务图 (DAG):
                 +----------+
            +--> | task 2   | --+
            |    | pending  |   |
+----------+     +----------+    +--> +----------+
| task 1   |                          | task 4   |
| completed| --> +----------+    +--> | blocked  |
+----------+     | task 3   | --+     +----------+
                 | pending  |
                 +----------+
```

## 实现代码

```python
#!/usr/bin/env python3
"""
s07: Task System - 任务系统

持久化到磁盘的任务图
- 状态: pending -> in_progress -> completed
- 依赖: blockedBy + blocks
- 自动解锁后续任务
"""

import os
import json
import subprocess
from pathlib import Path
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()
TASKS_DIR = WORKDIR / ".tasks"


class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        max_id = 0
        for f in self.dir.glob("task_*.json"):
            try:
                task = json.loads(f.read_text())
                max_id = max(max_id, task.get("id", 0))
            except:
                pass
        return max_id

    def _save(self, task):
        f = self.dir / f"task_{task['id']}.json"
        f.write_text(json.dumps(task, indent=2, ensure_ascii=False))

    def _load(self, task_id):
        f = self.dir / f"task_{task_id}.json"
        return json.loads(f.read_text())

    def create(self, subject: str, description: str = "", blocked_by: list = None):
        task = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": blocked_by or [],
            "blocks": [],
            "owner": ""
        }
        self._save(task)
        self._next_id += 1
        return json.dumps(task, indent=2, ensure_ascii=False)

    def update(self, task_id: int, status: str = None, add_blocked_by: list = None):
        task = self._load(task_id)
        if status:
            task["status"] = status
            if status == "completed":
                self._clear_dependency(task_id)
        if add_blocked_by:
            task["blockedBy"] = task.get("blockedBy", []) + add_blocked_by
        self._save(task)
        return json.dumps(task, indent=2, ensure_ascii=False)

    def _clear_dependency(self, completed_id):
        for f in self.dir.glob("task_*.json"):
            task = json.loads(f.read_text())
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)

    def list_all(self) -> str:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "(无任务)"
        lines = []
        for t in tasks:
            status_icon = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
            blocked = f" (blocked by {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{status_icon} Task {t['id']}: {t['subject']}{blocked}")
        return "\n".join(lines)

    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2, ensure_ascii=False)


TASKS = TaskManager(TASKS_DIR)


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
        if limit:
            lines = text.splitlines()[:limit]
            return "\n".join(lines) + f"\n... ({limit} 行)"
        return text[:50000]
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


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        text = safe_path(path).read_text(encoding="utf-8")
        if old_text not in text:
            return "Error: 未找到文本"
        safe_path(path).write_text(text.replace(old_text, new_text), encoding="utf-8")
        return f"成功编辑: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


TOOLS = [
    {"name": "bash", "description": "Execute bash",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Edit file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "task_create", "description": "Create a task",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}, "blocked_by": {"type": "array", "items": {"type": "integer"}}}, "required": ["subject"]}},
    {"name": "task_update", "description": "Update task status",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["task_id", "status"]}},
    {"name": "task_list", "description": "List all tasks",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "task_get", "description": "Get task details",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", ""), kw.get("limit")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: run_edit(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
    "task_create": lambda **kw: TASKS.create(kw.get("subject", ""), kw.get("description", ""), kw.get("blocked_by")),
    "task_update": lambda **kw: TASKS.update(kw.get("task_id"), kw.get("status")),
    "task_list": lambda **kw: TASKS.list_all(),
    "task_get": lambda **kw: TASKS.get(kw.get("task_id")),
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    while True:
        response = client.messages.create(
            model=MODEL,
            system="You are a helpful assistant with task management capabilities.",
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
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
    print("s07: Task System - 任务系统演示")
    print("=" * 50)
    prompt = "Create 3 tasks: Setup project, Write code, Write tests with dependencies in order"
    result = agent_loop(prompt, client)
    print(f"最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()