# Codex

## 数据落点

| 用途 | 典型路径 | 能否移动 |
| --- | --- | --- |
| 配置与索引 | `C:\Users\<user>\.codex` | 固定路径，不搬 |
| 聊天索引 | `.codex\state_5.sqlite` 的 `threads` 表 | 搬数据后必须改 `cwd` |
| 项目根 | `.codex\state_5.sqlite` 的 `project_roots` 表 | 同上 |
| MCP 配置 | `.codex\config.toml` | 改了 MCP 服务路径要同步 |
| 对话工作区 | `Documents\Codex\<日期>\<任务>\` | ✅ 可迁到 `chats\` |
| 项目 | `D:\codex项目\*` 等 | ✅ 到 `projects\` |

## 索引是 SQLite，必须一起改

只搬目录不改索引 → 侧栏还指向旧路径，表现为"项目打不开 / 历史没了"。

```python
con = sqlite3.connect('file:state_5.sqlite?mode=ro', uri=True)
con.execute("select id, cwd from threads where cwd like '%旧根%'").fetchall()
con.execute("select path from project_roots where path like '%旧根%'").fetchall()
```

改的时候：

1. 先用 backup API 做一致性快照
2. 单事务提交
3. `pragma quick_check` 必须 ok
4. 复查：指向旧根的 `threads.cwd` 应为 0

## `config.toml` 的 MCP

```toml
[mcp_servers.xxx]
args = ['D:\...\server.mjs']
```

- 改了 `server.mjs` 的位置 → 改这里，并重连 MCP
- `server.mjs` **内部**引用其他仍在原地的目录时，不要跟着改（那是有效依赖）
- MCP 服务属于环境，不要放进 `projects\`

## venv

Codex 项目常带 venv。搬目录后：

- `python.exe` 还能用（靠 `pyvenv.cfg`）
- `pip.exe` / `uvicorn.exe` 等**会静默失败**（内嵌旧 shebang）
- 用 distlib 重建启动器，`--check` 全部 ok 才算过
- `pyvenv.cfg` 的 `command =` 里会留下旧路径，不影响运行

## 其他

- `AGENTS.md` / `README` 里写死的绝对路径属历史记录，不改
- 全局状态 `.codex-global-state.json` 里有大量旧的标签页/提示词路径，属 UI 历史，不必改
- 桌面快捷方式的 `IconLocation` 容易漏（Target 对了但图标还是旧路径）
