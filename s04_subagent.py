#!/usr/bin/env python3
"""
s04: Subagents - 子智能体

添加 task 工具用于派发子任务
子智能体拥有独立 messages[]，不污染主对话
子智能体只有基础工具（禁止递归）

关键: 大任务拆小，每个小任务干净的上下文。

参考: https://github.com/shareAI-lab/learn-claude-code/blob/main/docs/zh/s04-subagent.md
"""

import os
import subprocess
from pathlib import Path
from anthropic import Anthropic

# 配置
MODEL = "claude-sonnet-4-20250514"

PARENT_SYSTEM = """You are a helpful AI assistant. You have access to multiple tools:
- bash, read_file, write_file, edit_file: file operations
- task: spawn a subagent with fresh context

Use task tool to delegate work to subagents when appropriate."""

SUBAGENT_SYSTEM = """You are a subagent with fresh context. You have access to:
- bash, read_file, write_file, edit_file

Complete the task and return a summary. You do NOT have access to task tool."""

WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()


# ========== 基础工具函数 ==========

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
            return "\n".join(lines) + f"\n... ({limit} 行限制)"
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
        return f"成功写入: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return "Error: 未找到要替换的文本"
        file_path.write_text(text.replace(old_text, new_text), encoding="utf-8")
        return f"成功编辑: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


# ========== 子智能体实现 ==========

def run_subagent(prompt: str, client: Anthropic) -> str:
    """运行子智能体，返回摘要"""
    sub_messages = [{"role": "user", "content": prompt}]

    for _ in range(30):  # 安全限制
        response = client.messages.create(
            model=MODEL,
            system=SUBAGENT_SYSTEM,
            messages=sub_messages,
            tools=CHILD_TOOLS,
            max_tokens=8000,
        )

        sub_messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        # 执行工具调用
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = CHILD_HANDLERS.get(block.name)
                if handler:
                    try:
                        output = handler(**block.input)
                    except Exception as e:
                        output = f"Error: {str(e)}"
                else:
                    output = f"Unknown tool: {block.name}"

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output)[:50000]
                })

        sub_messages.append({"role": "user", "content": results})

    # 返回摘要文本，丢弃整个消息历史
    summary = "".join(
        b.text for b in response.content if hasattr(b, "text")
    ) or "(无摘要)"
    return summary


# ========== 工具定义 ==========

# 子智能体工具（不包含 task，防止递归）
CHILD_TOOLS = [
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
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
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
        "description": "Edit file",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"}
            },
            "required": ["path", "old_text", "new_text"]
        }
    }
]

CHILD_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", ""), kw.get("limit")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: run_edit(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
}

# 父智能体工具（包含 task）
PARENT_TOOLS = CHILD_TOOLS + [
    {
        "name": "task",
        "description": "Spawn a subagent with fresh context to complete a subtask. The subagent will return a summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task description for the subagent"}
            },
            "required": ["prompt"]
        }
    }
]

PARENT_HANDLERS = dict(CHILD_HANDLERS)


def run_task(prompt: str, client: Anthropic) -> str:
    """task 工具处理函数"""
    print(f"\n[SUBAGENT] 派发子任务: {prompt[:100]}...")
    result = run_subagent(prompt, client)
    print(f"[SUBAGENT] 返回摘要: {result[:200]}...")
    return result


PARENT_HANDLERS["task"] = lambda **kw: run_task(kw.get("prompt", ""), client=None)


# ========== 主循环 ==========

def agent_loop(query: str, client: Anthropic) -> str:
    """核心 Agent Loop（支持子智能体）"""
    # 修正 task handler
    PARENT_HANDLERS["task"] = lambda **kw: run_task(kw.get("prompt", ""), client)

    messages = [{"role": "user", "content": query}]

    while True:
        response = client.messages.create(
            model=MODEL,
            system=PARENT_SYSTEM,
            messages=messages,
            tools=PARENT_TOOLS,
            max_tokens=8000,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return response.content[0].text

        results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                handler = PARENT_HANDLERS.get(tool_name)

                if handler:
                    try:
                        output = handler(**block.input)
                    except Exception as e:
                        output = f"Error: {str(e)}"
                else:
                    output = f"Unknown tool: {tool_name}"

                print(f"\n[{tool_name}]")
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
        print("请设置 ANTHROPIC_API_KEY")
        return

    client = Anthropic(api_key=api_key)

    test_prompts = [
        "Use a subagent to find what testing framework this project uses",
        "Delegate: read all .py files and summarize what each one does",
        "Use a task to create a new module called utils.py, then verify it from here",
    ]

    print("=" * 50)
    print("s04: Subagents - 子智能体演示")
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