# Antigravity

## 数据落点

| 用途 | 典型路径 | 归类 |
| --- | --- | --- |
| 主程序 | `D:\Antigravity\app`（数百 MB） | `_runtime\app` |
| 更新包 | `...\data\updater` | `_runtime\data` |
| 安装包 | `...\_installer` | `_runtime\_installer` |
| 项目 | 用户创建 | `projects\` |
| 对话 | 会话数据库 | `chats\` |
| 自定义技能 | skills 目录 | `skills\` |

## 特点

- 三类运行时（app / updater / installer）体量大但更新频繁，**先预同步再原子切换**
- 用户配置通常在 `%USERPROFILE%\.gemini` 与 `AppData\Roaming\Antigravity`
- 内部 `conversations` 目录与会话数据联动，不要只搬一半

## 迁移方式

因为程序在运行时锁定严重，推荐"离线一键脚本 + 回退脚本"的组合：

1. **预先同步**：应用运行时先把 app/data/installer 复制到目标位置（不改原位）
2. **原子切换**：应用退出后，改联接、改快捷方式、删除原目录
3. **回退脚本**：反向操作，随时可还原

脚本要点：

- 先检查进程数为 0
- 复制用 `robocopy /E /COPY:DAT /DCOPY:T /R:2 /W:2`
- 切换前再校验一次文件数与字节
- 记录 journal，可回滚

## 验收

- 应用能启动，版本号不变
- 更新器仍能工作（检查 updater 配置指向新路径）
- 打开历史对话有内容
- 快捷方式 Target/WorkingDir/IconLocation 三者都指向新位置
