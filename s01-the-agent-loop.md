# s01: The Agent Loop (智能体循环)

`[ s01 ] s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12`

> *"One loop & Bash is all you need"* -- 一个工具 + 一个循环 = 一个智能体。
>
> **Harness 层**: 循环 -- 模型与真实世界的第一道连接。

## 问题

语言模型能推理代码, 但碰不到真实世界 -- 不能读文件、跑测试、看报错。没有循环, 每次工具调用你都得手动把结果粘回去。你自己就是那个循环。

## 解决方案

```
+--------+      +-------+      +---------+
|  User  | ---> |  LLM  | ---> |  Tool   |
| prompt |      |       |      | execute |
+--------+      +---+---+      +----+----+
                    ^                |
                    |   tool_result  |
                    +----------------+
                    (loop until stop_reason != "tool_use")
```

一个退出条件控制整个流程。循环持续运行, 直到模型不再调用工具。

## 工作原理

1. 用户 prompt 作为第一条消息。

```python
messages.append({"role": "user", "content": query})
```

2. 将消息和工具定义一起发给 LLM。

```python
response = client.messages.create(
    model=MODEL, system=SYSTEM, messages=messages,
    tools=TOOLS, max_tokens=8000,
)
```

3. 追加助手响应。检查 `stop_reason` -- 如果模型没有调用工具, 结束。

```python
messages.append({"role": "assistant", "content": response.content})
if response.stop_reason != "tool_use":
    return
```

4. 执行每个工具调用, 收集结果, 作为 user 消息追加。回到第 2 步。

```python
results = []
for block in response.content:
    if block.type == "tool_use":
        output = run_bash(block.input["command"])
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": output,
        })
messages.append({"role": "user", "content": results})
```

## 实现代码

```python
#!/usr/bin/env python3
"""
s01: The Agent Loop - 最简单的智能体循环实现

一个退出条件控制整个流程。循环持续运行, 直到模型不再调用工具。
"""

import os
import subprocess
from anthropic import Anthropic

# 配置
MODEL = "claude-sonnet-4-20250514"
SYSTEM = """You are a helpful AI assistant. You have access to a bash tool to execute commands.
When you need to run commands, use the bash tool. Otherwise, return your response directly."""


def run_bash(command: str) -> str:
    """执行 bash 命令并返回输出"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        return output if output else "(命令执行完成，无输出)"
    except subprocess.TimeoutExpired:
        return "Error: 命令执行超时"
    except Exception as e:
        return f"Error: {str(e)}"


# 定义 bash 工具
TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command in the terminal. Use this for file operations, running scripts, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute"
                }
            },
            "required": ["command"]
        }
    }
]


def agent_loop(query: str, client: Anthropic) -> str:
    """
    核心 Agent Loop 函数

    流程:
    1. 用户 prompt 作为第一条消息
    2. 将消息和工具定义一起发给 LLM
    3. 追加助手响应，检查 stop_reason
    4. 执行工具调用，收集结果，回到第2步
    """
    messages = [{"role": "user", "content": query}]

    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        # 追加助手响应
        messages.append({"role": "assistant", "content": response.content})

        # 检查是否还有工具调用，如果没有则结束
        if response.stop_reason != "tool_use":
            # 返回最终响应
            return response.content[0].text

        # 执行工具调用
        results = []
        for block in response.content:
            if block.type == "tool_use":
                command = block.input.get("command", "")
                print(f"\n[执行命令] {command}")
                output = run_bash(command)
                print(f"[输出结果] {output[:200]}...")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output
                })

        # 将工具结果作为 user 消息追加，继续循环
        messages.append({"role": "user", "content": results})


def main():
    # 创建 Anthropic 客户端
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("请设置 ANTHROPIC_API_KEY 环境变量")
        print("export ANTHROPIC_API_KEY=your_api_key")
        return

    client = Anthropic(api_key=api_key)

    # 测试 prompt
    test_prompts = [
        "Create a file called hello.py that prints 'Hello, World!'",
        "List all Python files in this directory",
        "What is the current git branch?",
    ]

    print("=" * 50)
    print("s01: The Agent Loop - 智能体循环演示")
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
```

## 试一试

```sh
# 设置 API Key
export ANTHROPIC_API_KEY=your_api_key

# 运行
python s01_agent_loop.py
```

试试这些 prompt:

1. `Create a file called hello.py that prints "Hello, World!"`
2. `List all Python files in this directory`
3. `What is the current git branch?`
4. `Create a directory called test_output and write 3 files in it`

## 总结

不到 30 行代码, 这就是整个智能体。后面 11 个章节都在这个循环上叠加机制 -- 循环本身始终不变。

- **核心**: `while True` + `stop_reason` 检查
- **工具**: 单一的 `bash` 工具
- **消息**: 累积式消息列表
- **控制流**: `stop_reason != "tool_use"` 退出条件