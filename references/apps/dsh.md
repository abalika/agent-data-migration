# DeepSeek Harness（DSH）

## 数据落点

| 用途 | 典型路径 | 能否移动 |
| --- | --- | --- |
| 数据根（DSH_HOME） | `D:\dsh-projects\home` | ✅ 到 `_runtime\home` |
| 历史会话 | `...\legacy-home` | ✅ |
| 项目 | 数据根同级的 `projects\` | ✅ 到 `projects\` |
| 交付物 | `chats\deliverables` | ✅ 到 `chats\` |
| 插件 | `dsh-mcp`、`dsh-mode-switch`、`dsh-session-delete`、`dsh-wb2api-widget` | ✅ 到 `_runtime\plugins\`，**必须重建链接** |
| 安装目录 | `D:\deepseekharnees\`（注意拼写） | ❌ 注册表卸载项、更新器绑定此路径 |
| npm 全局前缀 | `D:\npm-global` | ❌ 属 npm 环境，非应用私有 |

## 三个必须先确认的事实

### 1. `DSH_HOME` 是用户级环境变量

不只在 `Start-DSH.bat` 里。两处都要改，否则从别的入口启动会读到旧 home。

```powershell
[Environment]::SetEnvironmentVariable('DSH_HOME','D:\agents\dsh\_runtime\home','User')
```

### 2. 会话文件是多帧 zstd 容器（**最容易搞坏的地方**）

`session.v4.jsonl.zstd` 不是"一个 zstd 流"，而是**帧序列**：

```
帧1   {"type":"session",...}        ← 只有这一行
帧2   一批事件
帧3   一批事件
...
```

应用的读取器（`dsh-session-persistence-jsonl`）会：

1. 结构性扫帧（magic + 帧头 + 块结构）
2. 只解第 1 帧，断言"**恰好一行、且以换行结尾**"（`assertZstdHeaderFrame`）
3. 依次解其余帧，要求每帧都在**行边界**结束
4. 校验事件 `seq` 连续

**所以：只改会话头的 `cwd` 时，必须只重压第 1 帧，其余帧原样复制。**
把整个文件解压再压成单帧 → 首帧包含几百行 → 断言失败 → 会话被判为损坏 → 列表全空。

正确的重写方式：

```python
frames = split_zstd_frames(raw)          # [头帧, 数据帧...]
head = json.loads(frames[0][:-1])
head['cwd'] = new_cwd
new_head = json.dumps(head, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
out = compress(new_head) + b''.join(frames[1:])   # 其余帧原样拼回去
```

### 3. 会话目录名由 cwd 派生（slug）

```
D:\agents\dsh  ->  --D-agents-dsh--
D:\agents\dsh\projects\大六壬 -> --D-agents-dsh-projects-~5927~516D~58EC--
```

规则：盘符去掉冒号、路径分隔符变 `-`、非 ASCII 写成 `~XXXX`（四位大写十六进制）、
整体前后加 `--`。

改 cwd 时**目录名必须同步改**，否则应用按 cwd 推算目录时找不到文件。

自检：对每个会话，`slugify(header.cwd)` 应等于它所在的目录名。

## 重绑清单

| 层 | 位置 |
| --- | --- |
| L1 | 用户环境变量 `DSH_HOME` |
| L2 | `Start-DSH.bat` / `Start-DSH-Web.bat` 里的 `DSH_HOME_DIR`、`WORKDIR` |
| L2 | `home\cordis.patch.yml`、`home\profiles\desktop\cordis.patch.yml` 里的插件与可执行路径 |
| L3 | `home\storages\workspace.json` 的 `workspaces[*].path` |
| L4 | `home\storages\session_projcache.json`、`session_projcache\sessions\*.json` |
| L6 | `home\profiles\desktop\node_modules\<插件>` 与 `@scope/<插件>` 的符号链接 |
| L7 | 计划任务（脚本在 `_runtime\work\`）、桌面备份脚本 |

## 验收要点

```bash
# 1) 所有会话：首帧单行 + 目录名与 cwd 匹配 + seq 连续
#    （可用 scripts 里的模式自己写，或参考 pitfalls.md 第 1 条）

# 2) 工作区登记能定位到文件（注意旧格式文件名：session.jsonl.zstd 没有 .v4）
# 3) 工作区里不要留已删会话的登记 —— 点开会是空白
```

启动后应满足：工作区数量不变、每个工作区能展开出会话、随便点开一条有内容。

## 已知项

- 有些会话结构上就没有任何消息事件（只有权限/沙箱/审批/斜杠命令），点开本来就是空白，不是迁移造成的
- `legacy-home.staging` 可能是不完整的历史副本，不要当成现用数据
