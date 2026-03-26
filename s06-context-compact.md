# s06: Context Compact (上下文压缩)

`s01 > s02 > s03 > s04 > s05 > [ s06 ] | s07 > s08 > s09 > s10 > s11 > s12`

> *"上下文总会满, 要有办法腾地方"* -- 三层压缩策略, 换来无限会话。
>
> **Harness 层**: 压缩 -- 干净的记忆, 无限的会话。

## 问题

上下文窗口是有限的。读一个 1000 行的文件就吃掉 ~4000 token; 读 30 个文件、跑 20 条命令, 轻松突破 100k token。不压缩, 智能体根本没法在大项目里干活。

## 解决方案

三层压缩, 激进程度递增:

```
Every turn:
+------------------+
| Tool call result |
+------------------+
        |
        v
[Layer 1: micro_compact]        (silent, every turn)
  Replace tool_result > 3 turns old
  with "[Previous: used {tool_name}]"
        |
        v
[Check: tokens > 50000?]
   |               |
   no              yes
   |               |
   v               v
continue    [Layer 2: auto_compact]
              Save transcript to .transcripts/
              LLM summarizes conversation.
              Replace all messages with [summary].
                    |
                    v
            [Layer 3: compact tool]
              Model calls compact explicitly.
              Same summarization as auto_compact.
```

## 工作原理

1. **第一层 -- micro_compact**: 每次 LLM 调用前, 将旧的 tool result 替换为占位符。

2. **第二层 -- auto_compact**: token 超过阈值时, 保存完整对话到磁盘, 让 LLM 做摘要。

3. **第三层 -- compact tool**: 手动触发同样的摘要机制。

完整历史通过 transcript 保存在磁盘上。信息没有真正丢失, 只是移出了活跃上下文。

## 实现代码

```python
#!/usr/bin/env python3
"""
s06: Context Compact - 上下文压缩

三层压缩策略:
1. micro_compact: 每次替换旧 tool_result 为占位符
2. auto_compact: token 超过阈值时保存并摘要
3. compact tool: 手动触发摘要

关键: 上下文总会满，要有办法腾地方。
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
KEEP_RECENT = 3  # 保留最近 3 个 tool_result


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


# ========== 压缩函数 ==========

def estimate_tokens(text: str) -> int:
    """简单估算 token 数量"""
    return len(text) // 4


def micro_compact(messages: list) -> list:
    """第一层: 替换旧的 tool_result 为占位符"""
    tool_results = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for j, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_name = part.get("tool_use_id", "unknown")
                    tool_results.append((i, j, part, tool_name))

    if len(tool_results) <= KEEP_RECENT:
        return messages

    # 替换旧的结果
    for i, j, part, tool_name in tool_results[:-KEEP_RECENT]:
        if len(part.get("content", "")) > 100:
            part["content"] = f"[Previous: used tool]"

    return messages


def save_transcript(messages: list) -> str:
    """保存对话记录到磁盘"""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return str(transcript_path)


def auto_compact(messages: list, client: Anthropic) -> list:
    """第二层: 保存完整对话并让 LLM 摘要"""
    # 保存 transcript
    transcript_path = save_transcript(messages)
    print(f"\n[COMPACT] 保存对话到: {transcript_path}")

    # LLM 摘要
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            f"""Summarize this conversation concisely for continuity. Include:
1. What task was being worked on
2. What tools have been used
3. Current status and next steps

Conversation:
{json.dumps(messages, default=str)[:80000]}"""}],
        max_tokens=2000,
    )

    summary = response.content[0].text
    print(f"[COMPACT] 摘要: {summary[:200]}...")

    return [
        {"role": "user", "content": f"[Compressed conversation]\n\n{summary}"},
        {"role": "assistant", "content": "Understood. Continuing."},
    ]


# ========== 工具定义 ==========

TOOLS = [
    {"name": "bash", "description": "Execute bash command",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Edit file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "compact", "description": "Manually compress the conversation to free up context",
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
    """核心 Agent Loop (支持上下文压缩)"""
    messages = [{"role": "user", "content": query}]
    manual_compact = False

    while True:
        # 第一层: micro_compact
        messages = micro_compact(messages)

        # 计算 token
        total_text = json.dumps(messages, default=str)
        tokens = estimate_tokens(total_text)

        # 第二层: auto_compact
        if tokens > TOKEN_THRESHOLD:
            print(f"\n[AUTO COMPACT] Token ({tokens}) 超过阈值 ({TOKEN_THRESHOLD})")
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

        # 执行工具
        results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                if tool_name == "compact":
                    manual_compact = True

                handler = TOOL_HANDLERS.get(tool_name)
                output = handler(**block.input) if handler else f"Unknown: {tool_name}"

                print(f"\n[{tool_name}]")
                print(f"[输出] {output[:200]}...")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })

        # 第三层: 手动压缩
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

    test_prompts = [
        "Read all Python files in the current directory one by one",
        "Use the compact tool to manually compress the conversation",
    ]

    print("=" * 50)
    print("s06: Context Compact - 上下文压缩演示")
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