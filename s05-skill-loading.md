# s05: Skills (技能加载)

`s01 > s02 > s03 > s04 > [ s05 ] s06 | s07 > s08 > s09 > s10 > s11 > s12`

> *"用到什么知识, 临时加载什么知识"* -- 通过 tool_result 注入, 不塞 system prompt。
>
> **Harness 层**: 按需知识 -- 模型开口要时才给的领域专长。

## 问题

你希望智能体遵循特定领域的工作流: git 约定、测试模式、代码审查清单。全塞进系统提示太浪费 -- 10 个技能, 每个 2000 token, 就是 20,000 token, 大部分跟当前任务毫无关系。

## 解决方案

```
System prompt (Layer 1 -- always present):
+--------------------------------------+
| You are a coding agent.              |
| Skills available:                    |
|   - git: Git workflow helpers        |  ~100 tokens/skill
|   - test: Testing best practices     |
+--------------------------------------+

When model calls load_skill("git"):
+--------------------------------------+
| tool_result (Layer 2 -- on demand):  |
| <skill name="git">                   |
|   Full git workflow instructions...  |  ~2000 tokens
|   Step 1: ...                        |
| </skill>                             |
+--------------------------------------+
```

第一层: 系统提示中放技能名称 (低成本)。第二层: tool_result 中按需放完整内容。

## 工作原理

1. 每个技能是一个目录, 包含 `SKILL.md` 文件和 YAML frontmatter。

```
skills/
  pdf/
    SKILL.md       # ---\n name: pdf\n description: Process PDF files\n ---\n ...
  code-review/
    SKILL.md       # ---\n name: code-review\n description: Review code\n ---\n ...
```

2. SkillLoader 递归扫描 `SKILL.md` 文件, 用目录名作为技能标识。

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills = {}
        for f in sorted(skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body}

    def get_descriptions(self) -> str:
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'."
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
```

3. 第一层写入系统提示。第二层不过是 dispatch map 中的又一个工具。

## 实现代码

```python
#!/usr/bin/env python3
"""
s05: Skills - 技能加载

两层知识：
- 系统提示：技能名称列表（低成本）
- tool_result：按需加载完整内容

关键: 用到什么知识，临时加载什么知识。
"""

import os
import re
import subprocess
from pathlib import Path
from anthropic import Anthropic

MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path("/Users/awan/.claude/skills/gstack/aistudy").resolve()
SKILLS_DIR = WORKDIR / "skills"


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


# ========== SkillLoader ==========

class SkillLoader:
    """技能加载器"""

    def __init__(self, skills_dir: Path):
        self.skills = {}
        if skills_dir.exists():
            self._load_skills(skills_dir)

    def _load_skills(self, skills_dir: Path):
        """加载所有 SKILL.md 文件"""
        for f in sorted(skills_dir.rglob("SKILL.md")):
            try:
                text = f.read_text(encoding="utf-8")
                meta, body = self._parse_frontmatter(text)
                name = meta.get("name", f.parent.name)
                self.skills[name] = {"meta": meta, "body": body, "path": str(f)}
            except Exception as e:
                print(f"Warning: 加载技能失败 {f}: {e}")

    def _parse_frontmatter(self, text: str):
        """解析 YAML frontmatter"""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                # 简单的 frontmatter 解析
                meta_text = parts[1].strip()
                body = parts[2].strip()
                meta = {}
                for line in meta_text.split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        meta[key.strip()] = val.strip()
                return meta, body
        return {}, text

    def get_descriptions(self) -> str:
        """获取技能描述列表（用于系统提示）"""
        if not self.skills:
            return "  (无技能)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """获取技能完整内容"""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {list(self.skills.keys())}"
        body = skill["body"]
        return f'<skill name="{name}">\n{body}\n</skill>'

    def list_skills(self) -> str:
        """列出所有可用技能"""
        if not self.skills:
            return "(无技能)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "")
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)


# 初始化技能加载器
SKILL_LOADER = SkillLoader(SKILLS_DIR)

# 创建示例技能
def create_sample_skills():
    """创建示例技能目录"""
    sample_skills = {
        "git-workflow": {
            "name": "git-workflow",
            "description": "Git workflow best practices",
            "body": """# Git Workflow

Follow this workflow for all changes:

1. Create a feature branch from main
2. Make small, focused commits
3. Write meaningful commit messages
4. Open a PR for review
5. Squash and merge after approval

Never commit directly to main."""
        },
        "code-review": {
            "name": "code-review",
            "description": "Code review checklist",
            "body": """# Code Review Checklist

Checklist for reviewing code:

1. Does the code work as intended?
2. Is the code readable and well-structured?
3. Are there any security concerns?
4. Is there adequate test coverage?
5. Are error cases handled properly?"""
        },
    }

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for name, skill in sample_skills.items():
        skill_dir = SKILLS_DIR / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"""---
name: {skill['name']}
description: {skill['description']}
---

{skill['body']}"""
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    # 重新加载
    SKILL_LOADER._load_skills(SKILLS_DIR)


# ========== 工具定义 ==========

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command",
        "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
    },
    {
        "name": "read_file",
        "description": "Read file contents",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}
    },
    {
        "name": "write_file",
        "description": "Write file contents",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
    },
    {
        "name": "edit_file",
        "description": "Edit file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}
    },
    {
        "name": "load_skill",
        "description": "Load a skill with full instructions. Use this when you need domain-specific knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Skill name to load"}},
            "required": ["name"]
        }
    }
]

TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw.get("path", ""), kw.get("limit")),
    "write_file": lambda **kw: run_write(kw.get("path", ""), kw.get("content", "")),
    "edit_file": lambda **kw: run_edit(kw.get("path", ""), kw.get("old_text", ""), kw.get("new_text", "")),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw.get("name", "")),
}


def agent_loop(query: str, client: Anthropic) -> str:
    """核心 Agent Loop"""
    system = f"""You are a coding agent at {WORKDIR}.

Skills available:
{SKILL_LOADER.get_descriptions()}

Use load_skill to load skills when needed."""

    messages = [{"role": "user", "content": query}]

    while True:
        response = client.messages.create(
            model=MODEL,
            system=system,
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

                if tool_name == "load_skill":
                    print(f"\n[LOAD SKILL] {kw.get('name')}")

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

    # 创建示例技能
    create_sample_skills()

    client = Anthropic(api_key=api_key)

    test_prompts = [
        "What skills are available?",
        "Load the git-workflow skill and follow its instructions",
        "I need to do a code review -- load the code-review skill first",
    ]

    print("=" * 50)
    print("s05: Skills - 技能加载演示")
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