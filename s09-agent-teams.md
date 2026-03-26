# s09: Agent Teams (智能体团队)

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > [ s09 ] s10 > s11 > s12`

> *"任务太大一个人干不完, 要能分给队友"* -- 持久化队友 + JSONL 邮箱。

## 问题

子智能体是一次性的，没有身份和跨调用记忆。

## 解决方案

- TeammateManager: 维护团队名册
- MessageBus: JSONL 收件箱通信

## 工具

- spawn_teammate: 创建队友
- team_list: 列出团队
- send_message: 发送消息
- check_inbox: 检查收件箱