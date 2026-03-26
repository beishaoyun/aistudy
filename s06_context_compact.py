#!/usr/bin/env python3
"""
s06: Context Compact - 上下文压缩

三层压缩策略:
1. micro_compact: 每次替换旧 tool_result 为占位符
2. auto_compact: token 超过阈值时保存并摘要
3. compact tool: 手动触发摘要

关键: 上下文总会满，要有办法腾地方。

参考: https://github.com/shareAI-lab/learn-claude-code/blob/main/docs/zh/s06-context-compact.md
"""

import os
import json
import time
import subprocess
from pathlib import Path
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOKEN_THRESHOLD = 50000
KEEP_RECENT = 3


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


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def micro_compact(messages: list) -> list:
    tool_results = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for j, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((i, j, part))

    if len(tool_results) <= KEEP_RECENT:
        return messages

    for i, j, part in tool_results[:-KEEP_RECENT]:
        if len(part.get("content", "")) > 100:
            part["content"] = f"[Previous: used tool]"

    return messages


def save_transcript(messages: list) -> str:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return str(transcript_path)


def auto_compact(messages: list, client: Anthropic) -> list:
    transcript_path = save_transcript(messages)
    print(f"\n[COMPACT] 保存对话到: {transcript_path}")

    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            f"""Summarize this conversation concisely: {json.dumps(messages, default=str)[:80000]}"""}],
        max_tokens=2000,
    )

    summary = response.content[0].text
    print(f"[COMPACT] 摘要: {summary[:200]}...")

    return [
        {"role": "user", "content": f"[Compressed conversation]\n\n{summary}"},
        {"role": "assistant", "content": "Understood. Continuing."},
    ]


TOOLS = [
    {"name": "bash", "description": "Execute bash command",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Edit file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "compact", "description": "Manually compress conversation",
     "input_schema": {"type": "object", "properties": {}}}
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", ""), kw.get("limit")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: run_edit(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
    "compact": lambda **kw: "[Compacting conversation...]",
}


def agent_loop(query: str, client: Anthropic) -> str:
    messages = [{"role": "user", "content": query}]
    manual_compact = False

    while True:
        messages = micro_compact(messages)

        total_text = json.dumps(messages, default=str)
        if estimate_tokens(total_text) > TOKEN_THRESHOLD:
            print(f"\n[AUTO COMPACT] Token 超过阈值")
            messages = auto_compact(messages, client)

        response = client.messages.create(
            model=MODEL,
            system="You are a helpful assistant.",
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
                if tool_name == "compact":
                    manual_compact = True

                handler = TOOL_HANDLERS.get(tool_name)
                output = handler(**block.input) if handler else f"Unknown: {tool_name}"

                print(f"\n[{tool_name}] {output[:200]}...")

                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        if manual_compact:
            messages = auto_compact(messages, client)
            manual_compact = False
        else:
            messages.append({"role": "user", "content": results})


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置 ANTHROPIC_API_KEY")
        return

    client = Anthropic(api_key=api_key)

    print("=" * 50)
    print("s06: Context Compact - 上下文压缩演示")
    print("=" * 50)

    prompt = "Read all Python files in the current directory one by one"
    print(f"\n测试: {prompt}")
    result = agent_loop(prompt, client)
    print(f"\n最终响应: {result[:500]}...")


if __name__ == "__main__":
    main()