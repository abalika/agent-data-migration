# agent-data-migration

把 AI agent / 桌面应用散落在磁盘各处的数据，收敛成"**一个应用一个根**"的规范结构——
并且保证：**应用能启动、历史能打开、引用零残留、随时可回滚**。

> Migrate scattered AI-agent data into a unified directory layout, with dry-run,
> reference rebinding, verification and one-command rollback.

这不是"搬家脚本"，而是一整套**先问、再测、再搬、再验**的流程，
由四次真实迁移（Codex / WorkBuddy / DeepSeek Harness / Antigravity）反推而成，
里面每一条"注意"都对应一次真实事故。

---

## 为什么需要它

AI agent 用久了，数据会散成这样：

```
D:\codex项目\              项目
C:\Users\me\.codex\        索引数据库
D:\WorkBuddy项目\          另一批项目
C:\Users\me\.workbuddy\    数据根 + 2GB 运行时
D:\dsh-projects\home\      会话
D:\npm-global\             全局依赖
```

直接搬目录的三种典型下场：

1. **会话列表空了** —— 文件的内部格式被你重写了（例如多帧 zstd 被压成单帧）
2. **插件加载不了** —— `node_modules` 里的 `file:` 依赖是指向源码的符号链接，源码一走就断
3. **打开历史是空白** —— 数据库里的 `cwd` 还是旧路径

这个 skill 把这三类坑都做成了可执行的检查与脚本。

## 它解决什么

| 能力 | 说明 |
| --- | --- |
| **先确认目标** | `--list-apps` 列出本机有哪些 agent，**用户不确认就不动手** |
| **测绘** | 进程链 / 环境变量 / 注册表 / 磁盘特征，找出应用的所有落点 |
| **四分类** | `projects`（项目）、`chats`（对话）、`_runtime`（环境）、`maintenance`（归档） |
| **风险分级** | green / yellow / red，红级（运行中锁定的数据根）必须单独停机 |
| **执行** | 同盘 `rename`，跨盘"复制→校验→删源→建 junction"，校验不过绝不删源 |
| **七层重绑** | 环境变量、配置、数据库、索引、二进制内嵌、符号链接、系统集成 |
| **五层验收** | 结构 / 格式不变量 / 功能真跑 / 真实环境 / 演练沙盘 |
| **一键回滚** | `journal.json` 记录每步，可整体反向执行 |
| **编码不出乱码** | 控制台 UTF-8 + 报告带 BOM，Windows 中文环境实测 |

## 支持的应用

| 应用 | 支持程度 |
| --- | --- |
| DeepSeek Harness | 完整（含多帧 zstd 会话格式不变量） |
| WorkBuddy | 完整（junction 数据根、停机迁移、WAL 数据库） |
| Codex | 完整（`state_5.sqlite` 索引、venv 启动器） |
| Antigravity | 完整（app / updater / installer 三类分开） |
| Cursor / Claude / Windsurf / Trae / Cline | 有内置签名，按通用流程处理 |
| **其它任何应用** | **同样支持**：给名字或给目录即可 |

内置签名只是"识别快"，**不是能力边界**。
`--list-apps` 还会用启发式找出**没收录但像 agent 数据目录**的目录
（点目录、含 `sessions`/`projects`/`skills` 子目录、有 SQLite 等特征）。

## 安装

### 方式 A：作为 WorkBuddy 技能

解压到用户级技能目录：

```
~/.workbuddy/skills/agent-data-migration/
```

之后直接说：

> 用 agent-data-migration 帮我整理 DSH 的数据

### 方式 B：只用脚本（不需要任何 agent）

只依赖 **Python 3.10+ 和 Windows 自带的 PowerShell**（`robocopy` 用系统自带）。

```bash
git clone https://github.com/abalika/agent-data-migration.git
cd agent-data-migration
python scripts/discover.py --list-apps
```

> 目前面向 **Windows**（用了 junction、robocopy、Restart Manager）。
> 脚本对 Linux/macOS 做了降级处理，但核心搬运链路按 Windows 设计。

## 首跑示例（5 分钟）

假设要整理 DeepSeek Harness 的数据。

### ① 先问：本机有哪些 agent？

```bash
python scripts/discover.py --list-apps
```

```
== 已知 agent（有内置签名，识别最准）==
  1. workbuddy      证据分 7   进程链命中；数据目录 C:\Users\me\.workbuddy
  2. dsh            证据分 5   环境变量 DSH_HOME=...；数据目录 C:\Users\me\.dsh
  3. codex          证据分 2   数据目录 C:\Users\me\.codex

== 未收录但疑似 agent 数据目录（启发式发现）==
  1. .codebuddy     特征分 6   点目录；含 projects/sessions/skills
```

**这一步只给建议。确认目标后再往下走。**

### ② 测绘

```bash
python scripts/discover.py --app dsh --paths "D:\dsh-projects" --out inventory.json
```

得到 `inventory.json`：进程证据、环境变量、卸载项、每个候选目录的规模与配置线索。

### ③ 规划

```bash
python scripts/plan.py --inventory inventory.json \
    --root D:\agents\dsh --expand D:\dsh-projects --out plan.json
```

产出 `plan.json` + `plan.txt`，每项标了分类、风险、方式、是否需停机。

**打开 `plan.txt` 审一遍。** 分类错了直接改 JSON 再跑，不影响执行。

### ④ 演练 + 执行

```bash
python scripts/apply.py --plan plan.json --dry-run    # 只检查，不动文件
python scripts/apply.py --plan plan.json              # 逐项确认
```

执行前把应用退出（按可执行文件路径前缀确认 0 进程）。

### ⑤ 验收

```bash
python scripts/verify.py --plan plan.json
```

```
V1 目标存在 / 源处理正确
  [PASS] 全部目标目录存在
  [PASS] 源已正确处理（改名消失 / 复制后变联接）
V2 新根下无悬空链接
  [PASS] 悬空符号链接/联接 = 0
V3 数量一致性
  [PASS] 目标文件数不少于计划基线
结果：PASS 5 / FAIL 0
```

**脚本验完还要再确认两件事**：

- 打开一条历史会话，**有内容**（不是"文件在"）
- 从新位置跑一次 `node --version` / `python --version`

### 出问题？一键回滚

```bash
python scripts/apply.py --journal journal.json --rollback
```

## 产出物

| 文件 | 内容 |
| --- | --- |
| `inventory.json` | 测绘结果（进程/环境变量/注册表/目录规模） |
| `plan.json` | 机器可读的施工图 |
| `plan.txt` | 人可读的计划，**执行前必须审** |
| `journal.json` | 逐项操作日志，回滚依据 |
| `*-verify.txt` | 验收报告（UTF-8 BOM，记事本直接打开） |

## 目录结构

```
agent-data-migration/
├─ README.md                       本文件
├─ SKILL.md                        主流程（确认 → 测绘 → 规划 → 执行 → 重绑 → 验收）
├─ references/
│  ├─ discovery.md                 怎么从应用本体找数据（设置/右键/命令行）
│  ├─ rebinding.md                 七层引用逐层重绑
│  ├─ verification.md              五层验收
│  ├─ platform.md                  junction / robocopy / SQLite WAL / ACL / 编码
│  ├─ pitfalls.md                  23 条真实陷阱（症状 → 根因 → 处置）
│  └─ apps/
│     ├─ dsh.md                    多帧 zstd 会话、DSH_HOME、slug 目录
│     ├─ workbuddy.md              junction 数据根、停机迁移、WAL
│     ├─ codex.md                  state_5.sqlite、venv 启动器
│     └─ antigravity.md            app / updater / installer
├─ scripts/
│  ├─ discover.py                  测绘（--list-apps / --app / --paths）
│  ├─ plan.py                      分类与风险计划
│  ├─ apply.py                     执行 / 演练 / 回滚
│  ├─ verify.py                    结构与数量验收
│  ├─ scan_links.py                扫悬空符号链接（含 @scope 层）
│  ├─ who-locks.ps1                查谁占用文件（Restart Manager）
│  └─ _console.py                  控制台 UTF-8 + 报告写 BOM
└─ assets/
   ├─ REPORT-template.md           迁移报告模板
   └─ skeleton-README.md           目标目录的说明模板
```

## 保守原则

这是不可逆操作，所以：

- **目标应用没确认不动手**，计划没审过不执行
- 每个阶段结束都停下来，把结果给用户看，等确认再进下一阶段
- 只做点名的范围，不"顺手"整理别的东西
- 找不到目录会明确报错，**不会静默生成空清单**
- 出了问题**先回滚再排查**，不在坏状态上继续修

## 常见问题

**Q：会不会把我的历史对话删掉？**
不会。脚本只移动目录和建联接，不删用户内容；只有跨盘复制在"文件数与字节数校验通过"后才删源，且全部可回滚。

**Q：为什么用 junction 不用符号链接？**
Junction 不需要管理员权限，可以跨卷，对应用完全透明。
注意 Python 的 `os.path.islink()` 认不出 junction，判据要用 reparse point 属性。

**Q：Linux / macOS 能用吗？**
流程和文档通用，但 `apply.py` 的跨盘复制和 junction 是 Windows 实现。
在这些平台上建议手动执行"重绑 + 验收"两步。

**Q：会不会动注册表/系统设置？**
只读注册表卸载项用于判断安装目录。不会改安全策略，也不绕过任何审批机制。

## 贡献

欢迎补充：

- 新应用的适配文档（`references/apps/<名字>.md`）
- 新踩到的坑（`references/pitfalls.md`，按"症状 → 根因 → 处置"）
- 平台机制校正（`references/platform.md`）

提交前请本地跑一遍：

```bash
python -m py_compile scripts/*.py
python scripts/discover.py --list-apps
```

确认脚本能编译、候选列表能出来，再提 PR。

## 许可

MIT License。

---

*由四次真实迁移的事故清单整理而成：会话列表全空、插件异常、批处理乱码、
WAL 静默丢数据、venv 静默失败、环境变量漏改、链接悬空……每一条都已写进流程。*
