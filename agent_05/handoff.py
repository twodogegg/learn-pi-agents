"""任务转移（handoffs）示例。

对应文档：
- https://openai.github.io/openai-agents-python/zh/agents/#handoffs
- https://openai.github.io/openai-agents-python/zh/handoffs/

演示四件事：
1. `handoffs=[agent]`：直接传 Agent，SDK 会为它生成 `transfer_to_<name>` 工具；
2. `handoff_description`：一句话告诉我方模型“什么时候该转给它”，会被拼进默认工具描述；
3. `handoff()`：定制工具名/描述，并用 `input_type` + `on_handoff` 收集转移原因；
4. 转移前先向用户播报：指令里写“先说话再调用转移工具”，必要时再用 `on_handoff` 做代码兜底
   （模型不保证每次都先说话）。

为什么模型会转移：任务转移在 LLM 眼里就是一个普通函数工具（参数为空，或由 `input_type` 定义），
模型根据系统指令 + 工具描述自主决定调用，SDK 收到该调用后把控制权交给目标智能体。

任务转移和 `as_tool()` 的区别：转移后由被转移的智能体接管对话，它看到完整历史并继续回复；
`as_tool()` 只是把子智能体当一个函数调用，控制权始终留在原智能体。
"""

import asyncio
import sys

from pydantic import BaseModel

from agents import Handoff, ItemHelpers, MessageOutputItem, RunContextWrapper, handoff

from common import ask, make_agent, make_get_time


class EscalationData(BaseModel):
    """转移给人工前，先要求模型说明原因。"""

    reason: str


def on_escalate(ctx: RunContextWrapper[None], data: EscalationData) -> None:
    # 转移已确定、但新智能体还没接手时执行：适合记日志、建工单、写数据库。
    # ctx.context 是传给 Runner.run(..., context=...) 的对象，不是对话内容。
    print(f"\n[on_handoff] 升级给人工，原因：{data.reason}")


def build_agents():
    # 1) 直接传 Agent + handoff_description
    time_agent = make_agent(
        "你是时间专家。需要时间就调用 get_time，不要凭记忆回答。",
        [make_get_time()],
        name="time_agent",
        handoff_description="处理当前时间、时区换算、时间加减。",
    )
    math_agent = make_agent(
        "你是算术专家。只做算术，不查时间。",
        name="math_agent",
        handoff_description="处理纯算术计算，不涉及时间。",
    )
    human_agent = make_agent(
        "你是人工客服。安抚用户并记录诉求，告知后续处理方式。",
        name="human_agent",
        handoff_description="处理投诉、退款或你无法回答的问题。",
    )

    # 2) 用 handoff() 定制：换工具名、换描述、让模型带上转移原因
    escalate = handoff(
        human_agent,
        tool_name_override="escalate_to_human",
        tool_description_override=(
            "用户投诉、要求人工，或你确实无法处理时调用，并给出原因。"
            "调用前先用一句话告知用户你正在转接人工。"
        ),
        input_type=EscalationData,
        on_handoff=on_escalate,
    )

    # 指令里写死“先播报再转移”：转移工具是普通函数工具，模型可以边说话边调用，
    # 所以文本会先流式输出，然后才出现 transfer_to_* 调用。
    triage_agent = make_agent(
        "你是分流台。先判断问题类型再决定是否转移："
        "时间问题交给 time_agent，算术问题交给 math_agent，投诉或你无法处理时调用 escalate_to_human。"
        "转移前必须先用一句自然的话告诉用户转给谁、为什么（例如“这是时间问题，我帮您转给时间专家”），"
        "然后再调用转移工具。一次只转给一个智能体；转移之后不要再自己回答一遍。",
        name="triage",
        handoffs=[time_agent, math_agent, escalate],
    )
    return triage_agent


def print_transcript(result) -> None:
    """按顺序打印本次运行中每个智能体说过的话（含转移前的播报）。"""
    print("\n[对话记录]")
    for item in result.new_items:
        if isinstance(item, MessageOutputItem):
            print(f"- {item.agent.name}: {ItemHelpers.text_message_output(item)}")


def print_handoff_tools(agent) -> None:
    print("[可用的转移工具]")
    for item in agent.handoffs:
        if isinstance(item, Handoff):
            print(f"- {item.tool_name}（定制）：{item.tool_description}")
        else:
            name = Handoff.default_tool_name(item)
            print(f"- {name}（默认描述 + handoff_description）：{Handoff.default_tool_description(item)}")


async def main():
    triage_agent = build_agents()
    print_handoff_tools(triage_agent)

    questions = (
        sys.argv[1:] or ["现在东京几点？", "你们上个月多扣了我两次钱，我要投诉。"]
    )
    for question in questions:
        result = await ask(triage_agent, question)
        print_transcript(result)
        print(f"\n[最终接管对话的智能体] {result.last_agent.name}")
        print(f"[最终回答]\n{result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
