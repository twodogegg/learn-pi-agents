# pi-agent-02：给 agent 加工具（tools）

学习目标：让 agent 调用工具，并用工具的结果回答问题。

## 文件与运行

| 文件 | 作用 |
|---|---|
| `get-time.js` | 单个工具 `get_time`，打印完整的工具事件 |
| `multi-turn.js` | 两个有依赖的工具（`get_time` → `add_hours`），按 turn 对比 `text_delta` 与最终消息 |

```bash
npm i @earendil-works/pi-agent-core @earendil-works/pi-ai typebox
node pi-agent-02/get-time.js
node pi-agent-02/get-time.js "查一下 Mars/Base 的时间"   # 错误实验
node pi-agent-02/multi-turn.js
```

## 学到了什么

### 1. 工具的结构
一个工具就是一个对象：

- `name`、`label`、`description`（写给 LLM 看，决定它何时调用）
- `parameters`：用 `typebox` 的 `Type.Object(...)` 描述
- `execute(toolCallId, params, signal, onUpdate)`：返回 `{ content, details }`
  - `content` 给 LLM 看
  - `details` 留给自己（日志、UI），LLM 看不到

挂载方式：`agent.state.tools = [tool]`。

### 2. 一次运行的事件顺序
```
turn_start
  message_update (thinking_* / text_delta)
  tool_execution_start   ← 字段：toolCallId, toolName, args
  tool_execution_end     ← 字段：toolCallId, toolName, result, isError, durationMs
turn_end
turn_start               ← 模型拿到工具结果后的下一个 turn
  ...最终回答
turn_end
agent_end
```
一个 turn = 一次 LLM 调用 + 它触发的工具执行。

### 3. 同一批工具默认并行
模型一次回复里发出多个调用时，所有 `tool_execution_start` 先出现，之后才是各个 `end`（实测确认）。
文档说给工具设 `executionMode: "sequential"` 可让整批串行（我没有实测）。

### 4. 工具之间有依赖 → 多个 turn
`add_hours` 需要 `get_time` 返回的 `iso`，模型无法并行，只能：
turn 0 调 `get_time` → turn 1 调 `add_hours` → turn 2 给最终回答。

消息序列：`system → user → assistant → toolResult → assistant → toolResult → assistant`。
注意 `event.messages` 开头包含 `system` 消息。

### 5. `text_delta` 累计 ≠ `agent_end` 最后一条消息
- 累计 `text_delta`：整个运行中模型说过的所有话，含"我先去查一下……"这类过渡句
- `event.messages.at(-1)`：只有最后一个 turn 的文本

实测：174 字 vs 98 字，差的 76 字正好是前两个 turn 的过渡句。
做界面时：要最终答案取 `at(-1)`；要还原用户实时看到的内容，自己按 turn 累积 `text_delta`。

### 6. 工具出错时
- `execute` 抛异常，不需要自己 catch
- `tool_execution_end` 里 `isError: true`，`result.content` 就是异常消息，`details` 为空 `{}`
- 模型会读到这段错误文本并据此应对（本次实测：不编造、不乱重试、如实报告并继续完成其余任务）

### 7. 写工具的经验
- **错误信息要写清楚**：点明错在哪个参数（`Invalid time zone specified: Mars/Base`），模型才知道该放弃、重试还是换参数
- **工具结果可信，模型在结果之外自己补充的"知识"不一定可信**（实测中模型把火星协调时说成对应 Viking 1 着陆点，这是错的）
- `description` 和 `systemPrompt` 都会影响模型是否调用工具

## 注意事项

- **usage 只统计了最后一个 turn**：`event.messages.at(-1).usage` 不是整次运行的总量，要遍历所有 assistant 消息累加
- **pi 的 API 随版本变化**：旧版（0.85.x）文档里有 `shouldStopAfterTurn`，仓库 main 分支的文档说它已被移除，换成 `finishTurn`。写代码前先 `npm ls @earendil-works/pi-agent-core` 确认版本

## 暂时不学（以后遇到再说）

- `finishTurn`：在每个 turn 末尾决定"强制结束"或"强制继续"，用于防失控、验收不合格重做、省掉多余的总结轮
- `terminate: true`、`beforeToolCall`、`onUpdate` 流式进度

## 下一步：pi-agent-03

多轮对话与记忆：连续 `prompt()`、查看 `agent.state.messages`、`steer()` / `followUp()`。
