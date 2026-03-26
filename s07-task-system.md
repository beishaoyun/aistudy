# s07: Task System (任务系统)

`s01 > s02 > s03 > s04 > s05 > s06 | [ s07 ] s08 > s09 > s10 > s11 > s12`

> *"大目标要拆成小任务, 排好序, 记在磁盘上"* -- 文件持久化的任务图, 为多 agent 协作打基础。

## 问题

s03 的 TodoManager 只是内存中的扁平清单: 没有顺序、没有依赖、状态只有做完没做完。

## 解决方案

持久化到磁盘的任务图，每个任务有：
- 状态: pending -> in_progress -> completed
- 依赖: blockedBy + blocks
- 自动解锁后续任务

## 实现

```python
# 核心 TaskManager
class TaskManager:
    def create(self, subject, description="", blocked_by=None):
        task = {"id": self._next_id, "subject": subject,
                "status": "pending", "blockedBy": blocked_by or []}
        self._save(task)
        return task

    def update(self, task_id, status=None):
        task = self._load(task_id)
        if status == "completed":
            self._clear_dependency(task_id)
        self._save(task)
```

## 工具

- task_create: 创建任务
- task_update: 更新任务状态
- task_list: 列出所有任务
- task_get: 获取任务详情

## 总结

| 组件 | 之前 (s06) | 之后 (s07) |
|---|---|---|
| Tools | 5 | 8 |
| 规划模型 | 扁平清单 | 带依赖的任务图 |
| 持久化 | 内存 | 磁盘 (.tasks/) |