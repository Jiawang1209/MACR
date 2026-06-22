# tmux 集成方案:用一个终端跑多个 Agent(MACR 终端运行时)

> 阅读对象:`demo/tmux-master/`(C,约 8.6 万行)
> 整理日期:2026-06-22
> 配套阅读:`wispterm-craybot-源码接口笔记.md`、`WispTerm_源码解析与_Multi-Agent_Term_借鉴报告.md`
> 目的:把 tmux 的 **control mode** 抽成 MACR 的"多 Agent 终端运行时" —— 一个终端里开多个 pane,每个 pane 跑一个 Agent;MACR 用控制模式驱动它们、并以 tmux 为事实源接收事件。

---

## 0. 一句话结论

tmux **本身就是一个现成的"多 Agent 终端运行时"**:server 进程持有所有 session/window/pane,一个 pane 就是一个独立的进程(可以跑 `claude` 或 `codex`)。MACR 不用自己写 PTY/渲染/分屏,只要以 **control mode**(`tmux -CC`)连上 tmux,就能用纯文本命令**开 pane、喂输入、读屏、收事件**,把每个 pane 当作一个 Agent Runtime View。这正好补上 MACR 缺的终端运行时那一半 —— 而且比照搬 WispTerm 的 Zig Surface/PTY 轻得多。

为什么是 tmux 而不是直接 spawn 子进程(CrayBot 的 `LocalExecutor`):子进程模式一次只能"发命令收 stdout",看不到一个**交互式 Agent** 在终端里的实时状态(等待审批、需要输入);tmux 给的是**持久、可观测、可多路复用**的终端,Agent 重启/迁移时身份(`%pane-id`)还在。

---

## 1. tmux 的对象模型(直接当 MACR 的运行时模型)

三层对象,各有稳定 ID 前缀(这套 ID 命名值得 MACR 直接采用):

| 对象 | ID 前缀 | 含义 | 映射到 Multi-Agent Term |
|---|---|---|---|
| session | `$` (如 `$3`) | 一组 window 的容器,一个 attach 单位 | **一个 Agent 团队 / 一次 run** |
| window | `@` (如 `@7`) | session 里的一个"标签页",含一棵 pane 树 | **一个任务 / 一个工作区** |
| pane | `%` (如 `%12`) | 一个独立进程 + 终端,可输入可观测 | **一个 Agent Runtime View** |

> 对应报告的告诫:`%pane-id` 是**运行时显示/控制单元**(= `surface_id`),不是 Agent 身份本身。MACR 仍需把 `agent_id`(长期身份)、`session_id`(一次运行)、`%pane`(终端单元)分开存 —— Agent 可能 respawn 到新 pane,身份不变。

pane 树(横/纵分割)由 `layout` 表达,和 WispTerm 的 Split Tree 同构。

---

## 2. Control Mode 协议(`control.c` / `control-notify.c` / `cmd-queue.c`)

启动:`tmux -CC`(或 `tmux -C new-session ...`)。客户端进入控制模式后,**stdin 写命令、stdout 读响应+事件**,全程纯文本行。

### 2.1 命令 → 响应:guard 帧(`cmdq_guard`,`cmd-queue.c:825`)

你把普通 tmux 命令当文本行写进去(内部走 `cmd_parse_and_append`,`control.c:574`)。每条命令的输出被 guard 行包起来:

```
%begin <time> <cmd-number> <flags>
…命令的输出(如 list-panes 的每行)…
%end   <time> <cmd-number> <flags>      ← 成功
%error <time> <cmd-number> <flags>      ← 失败
```

源码:`control_write(c, "%%%s %ld %u %d", guard, t, number, flags)`。`<cmd-number>` 让你把响应和你发的第 N 条命令对上号 —— 这是做**请求/响应配对**的关键。

### 2.2 事件流:`%`-notification(异步,在 guard 帧之外)

tmux 主动推送的状态变化(`control-notify.c`),这是"事实源"的核心:

| 事件 | 触发 | 对 MACR 的意义 |
|---|---|---|
| `%output %<pane> <data>` | pane 产生了输出 | **每个 Agent 的实时输出流**(数据做了转义) |
| `%window-add @<w>` / `%window-close @<w>` | 窗口增删 | 任务/工作区生命周期 |
| `%window-renamed @<w> <name>` | 改名 | — |
| `%window-pane-changed @<w> %<p>` | 活动 pane 变化 | — |
| `%layout-change <w> <layout> <visible> <flags>` | 布局变化 | **权威布局**(见 2.3) |
| `%session-changed $<s> <name>` / `%sessions-changed` | 会话变化 | 团队/run 变化 |
| `%pause %<pane>` / `%continue %<pane>` | 输出流控 | 背压:pane 输出太快时暂停 |
| `%pane-mode-changed %<pane>` | 进入/退出 copy-mode 等 | — |
| `%client-detached` / `%client-session-changed` | 客户端变化 | — |

### 2.3 "tmux 是事实源"(报告第 7 节最推崇的设计)

MACR 发出 `split-window` 后**不要**自己乐观地改本地布局,而是**等 `%layout-change` / `%window-add` 回来**再更新状态。这避免本地 UI 状态和 tmux 真实状态分叉。把这个原则贯穿到任务编排:UI 可以显示"正在提交",但**绝不能把"提交了命令"等同于"任务完成"** —— 这与 MACR 的确定性门、与 WispTerm 的分层事实状态是同一条铁律。

---

## 3. 编排原语:命令 → MACR 操作(真实参数摘自各 `cmd-*.c`)

```bash
# 建团队会话(后台、打印 session_id)
new-session -d -s team1 -P -F '#{session_id}'
#   -d 不 attach  -s 名字  -P 打印新建对象  -F 格式

# 开一个 Agent:在新 window 或分屏里直接跑 claude/codex,打印 pane_id
split-window -h -t @7 -c /repo -P -F '#{pane_id}' claude
new-window   -t $3 -c /repo -P -F '#{pane_id}' 'codex'
#   -h 横分 / -v 纵分   -t 目标   -c 起始目录   末尾是要跑的命令(单独 argv,不经 shell 拼接)

# 给 Agent 喂输入(统一输入通道的 tmux 侧)
send-keys -t %12 -l '请实现 hello()'      # -l = literal,按字面发送
send-keys -t %12 Enter                     # 回车单独发(键名)
#   send-keys 是"人工/AI/远程"都能调的同一个写入口

# 读 Agent 的屏幕(快照 / 观测)
capture-pane -p -t %12 -S -200 -E - -J -e
#   -p 打到 stdout  -S 起始行(-200=往回 200 行)  -E - 到末尾
#   -J 折行合并  -e 保留转义序列(给启发式 detector 用)

# 把某个 pane 的输出持续管道给一个命令/文件(替代 %output 的落盘方式)
pipe-pane -O -t %12 'cat >> .macr/runs/<id>/pane-%12.log'
#   -O 只管 pane→命令方向   → 天然的 EventLog 落盘

# 枚举所有 Agent + 进程级状态(一次拿全)
list-panes -a -F '#{pane_id} #{pane_pid} #{pane_current_command} #{pane_dead} #{pane_dead_status} #{pane_current_path}'

# 查单个变量
display-message -p -t %12 -F '#{pane_current_command}'

# 生命周期
kill-pane -t %12
respawn-pane -t %12 claude        # 同 pane 重启 Agent(身份保留)
break-pane / join-pane            # pane 在 window 间迁移
select-layout tiled               # 排布
```

> 注意:`split-window` 在本版本里内部名是 `new-pane`(alias `splitw`/`newp`),参数 `[-bdefhIklPvWZ] [-c dir] [-e env] [-l size|-p %] [shell-command]`。`new-session` 参数 `[-AdDEPX][-c dir][-e env][-F fmt][-n name][-s name][-x w][-y h] [shell-command]`。

---

## 4. 三层状态观测(tmux + WispTerm OSC 7748 + 屏幕启发式)

把三种信号叠起来,正好对应报告第 10 节的分层事实状态:

| 层 | 来源 | 拿什么 | 可信度 |
|---|---|---|---|
| 进程级 | tmux `list-panes` 的 `pane_current_command` / `pane_dead` / `pane_dead_status` | 这个 pane 现在跑的是不是 `claude`/`codex`?进程是否退出、退出码 | 高(事实) |
| Agent 语义级 | WispTerm OSC 7748 hook(`claude_integration.zig`)→ 在 `%output` 流里出现 `\033]7748;…state=…` | `running/waiting_approval/done` 等权威状态 | 最高(100) |
| 屏幕启发式 | `capture-pane -e` → `agent_detector.detect()` | 没有 OSC 时,从屏幕文本猜状态 | 兜底(72–96) |

MACR 把这三层都投影成 `agent_detector.State` 枚举,写进 `.macr/runs/` 事件流。**严格区分**:tmux 说 `pane_dead status=0` 或屏幕出现 `done` 只是 `observed`;**MACR 的 Stage D 确定性门 + 测试转绿才是 `verified`**。

---

## 5. 与三大支柱的融合:谁补谁

| 能力 | 来源 | 角色 |
|---|---|---|
| 控制面:角色、确定性门、worktree 隔离、落盘、Task 语义 | **MACR(已有)** | 大脑 / 验收 / 审计 |
| 多 Agent 终端运行时:一终端多 pane、持久、可观测 | **tmux(本文)** | 身体 / 运行时 |
| Runtime Adapter:统一执行接口、安全 argv、单活动调度、制品回收 | **CrayBot(可照搬)** | MACR ↔ tmux 之间的适配层 |
| Agent 状态结构化上报 + 启发式兜底 | **WispTerm(可照搬)** | 观测层 |
| Surface/PTY/统一输入通道、ToolHost 能力边界 | **WispTerm(设计参考)** | 若将来要原生 UI 再用 |

落地形态:给 MACR 加一个 **`TmuxAdapter`**(实现 CrayBot 那套 `Executor`/Runtime Adapter 接口),内部通过 control mode 说话:
- `spawn(agent, cmd, dir)` → `split-window/new-window -P -F '#{pane_id}'`,记下 `%pane` ↔ `agent_id` 映射;
- `write(agent, text)` → `send-keys -t %pane -l … + Enter`;
- `observe(agent)` → 订阅 `%output` + 定期 `list-panes` + 解析 OSC 7748;
- `snapshot(agent)` → `capture-pane -p`;
- `kill/respawn(agent)` → `kill-pane`/`respawn-pane`。

MACR 现有的 `discuss` 角色(Leader/Worker/Reviewer)+ Stage D 门 + `worktree.py` 隔离不变,只是 Worker 从"spawn 一次性子进程"变成"在一个 tmux pane 里跑一个可观测、可交互的 Agent"。

---

## 6. "一个终端,N 个 Agent"最小配方(Phase 0 可跑)

```
1. MACR 起一个 control client:  tmux -CC new-session -d -s macr-run -P -F '#{session_id}'
2. 每个 Worker 开一个 pane:     split-window -t $S -c <worktree> -P -F '#{pane_id}' <claude|codex 命令>
   → 记 %pane ↔ agent_id;一个终端窗口 attach 上去,人能同时围观 N 个 Agent
3. 派发任务:                    send-keys -t %pane -l '<任务prompt>' ; send-keys -t %pane Enter
4. 观测:                        订阅 %output(含 OSC 7748)+ 轮询 list-panes(pane_dead/command)
5. 取证/审码:                   capture-pane -p + 读 worktree diff + 跑 --test-cmd
6. 门控:                        MACR 现有 Stage D 确定性门 + 人工门;只有 verified 才进 Completed
7. 落盘:                        pipe-pane 把每个 pane 的输出落到 .macr/runs/<id>/pane-%X.log
```

人在一个普通终端里 `tmux attach -t macr-run` 就能实况围观这队 Agent —— 这就是"用一个终端开启多个 Agent",且 MACR 的控制面、门控、审计全程在线。

---

## 7. 风险与注意(源码层面)

- **`%output` 转义 / 背压**:输出量大时 tmux 发 `%pause %<pane>`,要处理 `%continue` 才恢复;别假设 `%output` 不丢不停。
- **control mode 命令是文本行**:发的命令含特殊字符要按 tmux 语法转义;prompt 走 `send-keys -l` 字面发送、避免被当快捷键解释。
- **pane ≠ agent 身份**:respawn 后 `pane_pid` 变,`%pane-id` 在同一 pane 复用时也可能误配;MACR 要维护自己的 `agent_id` 映射并校验。
- **不是隔离边界**:tmux pane 之间不是沙箱;写入型 Worker 仍要靠 MACR 的 git worktree(以及将来容器)做文件隔离。
- **事实源优先**:任何"我以为开好了/写完了"都要等 tmux 事件或 `list-panes` 回执确认,不可乐观推断。

---

## 8. 校验说明

- 命令参数摘自源码 `cmd_entry`:`cmd-new-session.c:42`、`cmd-new-window.c:41`、`cmd-split-window.c:41`、`cmd-send-keys.c:36`、`cmd-capture-pane.c:45`、`cmd-pipe-pane.c:46`、`cmd-list-panes.c:41`。
- 控制协议摘自 `control.c`(`control_read_callback:553`、`control_append_data` 的 `%%output %%%u`、`control_write:412`)、`control-notify.c`(各 `%`-事件)、`cmd-queue.c:825 cmdq_guard`(`%begin/%end/%error`)。
- 格式变量见 `format.c`(`pane_id`、`pane_current_command`、`pane_dead`、`pane_dead_status`、`pane_current_path`)。
- 未在沙箱编译/运行 tmux;以上为静态阅读结论,具体行为(转义细节、版本差异)以源码与 `tmux.1` 手册为准。
