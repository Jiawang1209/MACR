# Stage B — subagent 解析器真实校准(待人工执行)

Stage B 的解析器(`macr/agents/trace.py`)对 Claude `stream-json` / Codex `--json` 的事件 schema 是**防御式假设**(见 spec §7)。需要用真实 CLI 校准一次:

```bash
.venv/bin/python scripts/smoke_collab.py <真实git仓库> "pytest -q" "一个小任务"
# 查看捕获的原始事件流:
ls .macr/runs/<run_id>/subagents/*.events.jsonl
```

对照真实事件的键名,若与 `parse_claude_stream` / `parse_codex_stream` 的假设(`type=="result"` 的 `result` 字段;`parent_tool_use_id`;`thread.started` 的 `thread_id`;`item.completed` 的 `agent_message.text`)有出入,就微调这两个解析器并补一条对应的合成-流单测。原始 `events.jsonl` 始终全保真落盘,即便摘要解析暂不完美也不丢可追踪性。
