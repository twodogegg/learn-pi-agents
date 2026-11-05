# 学习 OpenAI Agents SDK（Python）

本项目将原来的 Pi Agent 示例迁移到 OpenAI Agents SDK。依赖固定为 2026 年 11 月 5 日查到的最新正式版 `openai-agents==0.24.0`，要求 Python 3.10 或更高版本。

## 安装与配置

在项目根目录：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

默认沿用原项目的 OpenAI 兼容网关：`http://127.0.0.1:3425/v1`，模型为 `auto/auto`。可以通过环境变量调整：

```bash
export PI_BASE_URL="http://127.0.0.1:3425/v1"
export PI_API_KEY="你的网关密钥"
export PI_MODEL="auto/auto"
```

示例使用 Chat Completions 模型适配器，需要网关和模型支持流式输出及函数调用。连接其他网关时请按实际地址、密钥和模型名称配置；原来的 `PI_THINKING` 配置没有迁移，因为不同提供商的推理参数不统一。使用自定义网关时示例关闭了 OpenAI tracing。

## 示例

请在项目根目录运行：

```bash
python -m agent_01.hello
python -m agent_02.get_time
python -m agent_02.get_time "东京现在几点？"
python -m agent_02.multi_turn
python -m agent_03.memory
python -m agent_03.steer
python -m agent_04.finish_turn
```

| 示例 | 内容 |
| --- | --- |
| `agent_01.hello` | 创建 Agent、流式输出及最终回答。没有时间工具，因此不能保证当前时间准确。 |
| `agent_02.get_time` | 通过函数工具查询时间，默认演示无效时区的错误处理。 |
| `agent_02.multi_turn` | 链式调用时间工具，对比整次流式文本与最终回答。模型是否调用工具仍由模型决定。 |
| `agent_03.memory` | 使用内存 SQLiteSession 保存、查看和清空多轮会话。 |
| `agent_03.steer` | 工具运行期间准备新指令，通过调用前的输入过滤器在后续模型请求中注入，并在本次运行完成后发起追问。 |
| `agent_04.finish_turn` | 工具返回后直接结束运行，工具输出即最终结果。 |

`steer` 是近似示例：过滤器的改指令只进入模型请求，并不写入会话历史，也不能取消已发出的工具调用。追问是另一次 `Runner` 运行，并非 Pi 的 `followUp()` 队列。`stop_on_first_tool` 也不是 Pi 的通用 `finishTurn` 回调，它只针对工具输出。

SDK 使用方法可参考 [OpenAI Agents SDK 快速入门](https://openai.github.io/openai-agents-python/quickstart/)、[会话](https://openai.github.io/openai-agents-python/sessions/) 和 [流式输出](https://openai.github.io/openai-agents-python/streaming/)。
