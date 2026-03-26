#!/usr/bin/env python3
"""
s03: TodoWrite - 待办事项管理

添加 TodoManager 带状态管理
添加 todo 工具
添加 nag reminder（连续 3 轮不更新 todo 时注入提醒）

关键: 先列步骤再动手, 完成率翻倍。

参考: https://github.com/shareAI-lab/learn-claude-code/blob/main/docs/zh/s03-todo-write.md
"""

import os
import subprocess
from pathlib import Path
from anthropic import Anthropic

# 配置
MODEL = "claude-sonnet-4-20250514"
SYSTEM = """You are a helpful AI assistant. You have access to multiple tools to interact with the file system.
- bash: Execute bash commands
- read_file: Read file contents
- write_file: Create or overwrite a file
- edit_file: Edit a file
- todo: Manage task list with status (pending, in_progress, completed)

Always start with the todo tool to plan your approach, then execute step by step.
Only one task can be in_progress at a time."""

WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()


# ========== 基础工具函数 ==========

def safe_path(p: str) -> Path:
    """路径沙箱"""
    path = (WORKDIR / p).resolve()
    if not str(path).startswith(str(WORKDIR)):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        output = result.stdout + result.stderr
        return output if output else "(命令执行完成，无输出)"
    except Exception as e:
        return f"Error: {str(e)}"


def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text(encoding="utf-8")
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit]
            return "\n".join(lines) + f"\n... (已限制显示前 {limit} 行)"
        return text[:50000]
    except FileNotFoundError:
        return f"Error: 文件不存在: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"成功写入文件: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: 未找到要替换的文本"
        file_path.write_text(text.replace(old_text, new_text), encoding="utf-8")
        return f"成功编辑文件: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


# ========== TodoManager ==========

class TodoManager:
    """待办事项管理器"""

    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """更新待办事项"""
        validated = []
        in_progress_count = 0

        for item in items:
            status = item.get("status", "pending")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({
                "id": item.get("id", str(len(self.items))),
                "text": item.get("text", ""),
                "status": status
            })

        # 强制：同时只能有一个 in_progress
        if in_progress_count > 1:
            raise ValueError("Error: Only one task can be in_progress at a time")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """渲染待办列表"""
        if not self.items:
            return "(暂无待办事项)"
        lines = []
        for item in self.items:
            status_icon = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]"
            }.get(item["status"], "[?]")
            lines.append(f"{status_icon} {item['text']}")
        return "\n".join(lines)


# 全局 TodoManager 实例
TODO = TodoManager()


# ========== 工具定义 ==========

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write file contents",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Edit file by replacing text",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"}
            },
            "required": ["path", "old_text", "new_text"]
        }
    },
    {
        "name": "todo",
        "description": "Manage todo list: add, update, or check tasks. Status: pending, in_progress, completed. Only ONE task can be in_progress at a time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                        },
                        "required": ["id", "text", "status"]
                    }
                }
            },
            "required": ["items"]
        }
    }
]


# 工具分发器
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", ""), kw.get("limit")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: run_edit(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
    "todo": lambda **kw: TODO.update(kw.get("items", [])),
}


def agent_loop(query: str, client: Anthropic) -> str:
    """核心 Agent Loop（添加 nag reminder）"""
    messages = [{"role": "user", "content": query}]
    rounds_since_todo = 0  # 追踪自上次调用 todo 的轮数

    while True:
        # Nag reminder: 连续 3 轮以上不调用 todo 时注入提醒
        if rounds_since_todo >= 3 and messages:
            last = messages[-1]
            if last["role"] == "user" and isinstance(last.get("content"), list):
                # 插入文本提醒
                last["content"].insert(0, {
                    "type": "text",
                    "text": "<reminder>Update your todos to track progress.</reminder>"
                })
                print("\n[NAG REMINDER] 已注入提醒：更新待办事项")

        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return response.content[0].text

        # 执行工具调用
        results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                handler = TOOL_HANDLERS.get(tool_name)

                if handler:
                    try:
                        output = handler(**block.input)
                    except Exception as e:
                        output = f"Error: {str(e)}"
                else:
                    output = f"Unknown tool: {tool_name}"

                # 追踪 todo 调用
                if tool_name == "todo":
                    rounds_since_todo = 0
                    print(f"\n[TODO] 已更新待办事项")
                else:
                    rounds_since_todo += 1

                print(f"\n[{tool_name}] {block.input}")
                print(f"[输出] {output[:200]}...")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })

        messages.append({"role": "user", "content": results})


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置 ANTHROPIC_API_KEY 环境变量")
        return

    client = Anthropic(api_key=api_key)

    test_prompts = [
        "Refactor the file greet.py: add type hints, docstrings, and a main guard",
        "Create a Python package with __init__.py, utils.py, and tests/test_utils.py",
        "Review requirements.txt and add any missing dependencies",
    ]

    print("=" * 50)
    print("s03: TodoWrite - 待办事项管理演示")
    print("=" * 50)

    for i, prompt in enumerate(test_prompts, 1):
        print(f"\n{'='*50}")
        print(f"测试 {i}: {prompt}")
        print("=" * 50)
        result = agent_loop(prompt, client)
        print(f"\n最终响应: {result[:500]}...")
        print("-" * 50)


if __name__ == "__main__":
    main()