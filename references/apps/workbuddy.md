# WorkBuddy

## 数据落点

| 用途 | 典型路径 | 说明 |
| --- | --- | --- |
| 应用数据根 | `C:\Users\<user>\.workbuddy` | **固定路径**，应用没有换位置的设置 |
| 运行时二进制 | `...\.workbuddy\binaries` | node / python / PortableGit，2 GB 级 |
| 会话与工作区 | `D:\agents\workbuddy\chats\`、`projects\` | 用户内容 |
| 应用数据实体 | `D:\agents\workbuddy\_runtime\data` | 通过 junction 映射回 `.workbuddy` |
| 安装目录 | `D:\WorkBuddy` | 不动 |

## 关键机制：数据根用 junction 桥接

`.workbuddy` 是应用写死的路径，不能改。做法是**把实体放 D 盘，在原位建 junction**：

```
C:\Users\<user>\.workbuddy\logs      -> D:\agents\workbuddy\_runtime\data\logs
C:\Users\<user>\.workbuddy\profiles  -> ...
```

40+ 个目录这样映射。**这些 junction 是应用的数据入口，不是迁移残留，不要"清理"掉。**

剩下留在 C 盘的必须是真的文件（约 2 MB）：`workbuddy.db`(+wal/shm)、`settings.json`、
`SOUL.md`/`IDENTITY.md`/`USER.md`/`MEMORY.md`、`device-id`、`keyblob`、登录 nonce。
这些搬走会破坏启动或触发重新验证。

### `binaries` 必须停机迁移

应用运行时，shell、node、python 都从 `binaries` 里执行。**当前会话就跑在里面**，运行时搬不动。

正确流程：

1. 完全退出应用（按可执行文件路径前缀确认为 0）
2. robocopy 复制 → 校验 → 删源 → 建 junction
3. 重开应用，从联接执行 `node --version` / `python --version` / `bash --version` 验证

## 数据库

`workbuddy.db` 是 WAL 模式，正在使用。**不能直接 copy**：

```bash
sqlite3 "file:workbuddy.db?mode=ro" "VACUUM INTO 'backup.db'"
sqlite3 backup.db "PRAGMA integrity_check;"
```

关键字段：

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `sessions` | `cwd` | 会话工作目录，**路径可能是正斜杠**，用 `LIKE` 查 |
| `sessions` | `user_id` | 账号归属 |
| `workspaces` | `path` | 最近打开的工作区 |

表结构里**没有 `projects` 表**，`project_id` 无外键，不要去"修复"它。

## 两个账号

对话和项目是共用的，只有 `sessions.user_id` 隔离；资料目录按账号分。

若要把一个账号的资料对齐到 `账号资料\` 子目录：

1. 移动实体目录
2. **用 `[System.IO.Directory]::Delete($link,$false)` 删旧联接**（目标已移走时 `Remove-Item` 会失败）
3. `New-Item -ItemType Junction -Path <原位> -Target <新位置>` 重建
4. 透过联接读一个文件确认可访问

## 验收要点

- `.workbuddy` 下所有 junction 有效（`Target` 存在）
- `binaries` 从联接执行三套运行时都能出版本号
- 打开一条历史会话有内容
- 侧栏工作区数量与迁移前一致
- 数据库 `quick_check` ok

## 已知项

- 空的 `chats\Claw` 之类目录会被应用**重新创建**，删了还会回来，记录即可
- 侧栏标题可能仍显示旧目录名，是显示项，不影响功能
