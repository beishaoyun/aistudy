# s12: Worktree Task Isolation (Worktree 任务隔离)

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > [ s12 ]`

> *"各干各的目录, 互不干扰"* -- 任务管目标，worktree 管目录。

## 解决方案

给每个任务一个独立的 git worktree 目录，用任务 ID 绑定两边。

## 工具

- create_worktree: 创建 worktree
- list_worktrees: 列出所有 worktree

## 状态机

- Task: pending -> in_progress -> completed
- Worktree: absent -> active -> removed