# s02: Tool Use (工具使用)

`s01 > [ s02 ] s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12`

> *"加一个工具, 只加一个 handler"* -- 循环不用动, 新工具注册进 dispatch map 就行。
>
> **Harness 层**: 工具分发 -- 扩展模型能触达的边界。

## 问题

只有 `bash` 时, 所有操作都走 shell。`cat` 截断不可预测, `sed` 遇到特殊字符就崩, 每次 bash 调用都是不受约束的安全面。专用工具 (`read_file`, `write_file`) 可以在工具层面做路径沙箱。

关键洞察: 加工具不需要改循环。

## 解决方案

```
+--------+      +-------+      +------------------+
|  User  | ---> |  LLM  | ---> | Tool Dispatch    |
| prompt |      |       |      | {                |
+--------+      +---+---+      |   bash: run_bash |
                    ^           |   read: run_read |
                    |           |   write: run_wr  |
                    +-----------+   edit: run_edit |
                    tool_result | }                |
                                +------------------+

The dispatch map is a dict: {tool_name: handler_function}.
One lookup replaces any if/elif chain.
```

## 工作原理

1. 每个工具有一个处理函数。路径沙箱防止逃逸工作区。

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_read(path: str, limit: int = None) -> str:
    text = safe_path(path).read_text()
    lines = text.splitlines()
    if limit and limit < len(lines):
        lines = lines[:limit]
    return "\n".join(lines)[:50000]
```

2. dispatch map 将工具名映射到处理函数。

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"],
                                        kw["new_text"]),
}
```

3. 循环中按名称查找处理函数。循环体本身与 s01 完全一致。

## 实现代码

```python
#!/usr/bin/env python3
"""
s02: Tool Use - 工具使用与分发

扩展工具集：bash, read_file, write_file, edit_file
添加 dispatch map 实现工具分发
添加路径安全检查（沙箱）

关键洞察: 加工具不需要改循环。
"""

import os
import subprocess
from pathlib import Path
from anthropic import Anthropic

# 配置
MODEL = "claude-sonnet-4-20250514"
SYSTEM = """You are a helpful AI assistant. You have access to multiple tools to interact with the file system.
- bash: Execute bash commands
- read_file: Read file contents with optional line limit
- write_file: Create or overwrite a file
- edit_file: Edit a file by replacing old text with new text

Use the appropriate tool for each task."""

# 工作目录（沙箱根目录）
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()


def safe_path(p: str) -> Path:
    """路径沙箱：防止路径逃逸"""
    path = (WORKDIR / p).resolve()
    if not str(path).startswith(str(WORKDIR)):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """执行 bash 命令"""
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


def run_read(path: str, limit: int = None) -> str:
    """读取文件"""
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
    """写入文件"""
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"成功写入文件: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """编辑文件（替换文本）"""
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")

        if old_text not in text:
            return f"Error: 未找到要替换的文本: {old_text[:50]}..."

        new_content = text.replace(old_text, new_text)
        file_path.write_text(new_content, encoding="utf-8")
        return f"成功编辑文件: {path}"
    except FileNotFoundError:
        return f"Error: 文件不存在: {path}"
    except Exception as e:
        return f"Error: {str(e)}"


# 工具定义（供 LLM 使用）
TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command in the terminal. Use this for file operations, running scripts, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file from the filesystem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
                "limit": {"type": "integer", "description": "Maximum number of lines to read (optional)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with new content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Edit an existing file by replacing specific text with new text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace it with"}
            },
            "required": ["path", "old_text", "new_text"]
        }
    }
]


# 工具分发器：工具名 -> 处理函数
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", ""), kw.get("limit")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: run_edit(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
}


def agent_loop(query: str, client: Anthropic) -> str:
    """
    核心 Agent Loop 函数 (与 s01 完全相同)

    关键洞察: 加工具不需要改循环，只需要：
    1. 在 TOOLS 中添加工具定义
    2. 在 TOOL_HANDLERS 中添加处理函数
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

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return response.content[0].text

        # 使用 dispatch map 分发工具调用
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
        print("export ANTHROPIC_API_KEY=your_api_key")
        return

    client = Anthropic(api_key=api_key)

    test_prompts = [
        "Read the file requirements.txt",
        "Create a file called greet.py with a greet(name) function that returns 'Hello, {name}!'",
        "Edit greet.py to add a docstring to the greet function",
        "Read greet.py to verify the edit worked",
    ]

    print("=" * 50)
    print("s02: Tool Use - 工具使用与分发演示")
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
export ANTHROPIC_API_KEY=your_api_key
python s02_tool_use.py
```

试试这些 prompt:

1. `Read the file requirements.txt`
2. `Create a file called greet.py with a greet(name) function`
3. `Edit greet.py to add a docstring to the function`
4. `Read greet.py to verify the edit worked`

## 总结

**相对 s01 的变更：**

| 组件           | 之前 (s01)         | 之后 (s02)                     |
|----------------|--------------------|--------------------------------|
| Tools          | 1 (仅 bash)        | 4 (bash, read, write, edit)    |
| Dispatch       | 硬编码 bash 调用   | `TOOL_HANDLERS` 字典           |
| 路径安全       | 无                 | `safe_path()` 沙箱             |
| Agent loop     | 不变               | 不变                           |

**关键洞察**: 加工具不需要改循环。只需要在 TOOLS 中添加工具定义，在 TOOL_HANDLERS 中添加处理函数。循环本身与 s01 完全一致。