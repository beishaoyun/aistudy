#!/usr/bin/env python3
"""
s01: The Agent Loop - 最简单的智能体循环实现

一个退出条件控制整个流程。循环持续运行, 直到模型不再调用工具。

参考: https://github.com/shareAI-lab/learn-claude-code/blob/main/docs/zh/s01-the-agent-loop.md
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