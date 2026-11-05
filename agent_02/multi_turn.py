import asyncio
import sys

from agents import Runner

from common import add_hours, make_agent, make_get_time


async def main():
    agent = make_agent(
        "需要时间信息时调用 get_time；时间加减调用 add_hours。每次调用工具前先说明要做什么。",
        [make_get_time(), add_hours],
    )
    question = sys.argv[1] if len(sys.argv) > 1 else "查一下东京现在几点，再算出三小时后是几点。"
    result = Runner.run_streamed(agent, question)
    streamed = []
    async for event in result.stream_events():
        if event.type == "raw_response_event" and event.data.type == "response.output_text.delta":
            streamed.append(event.data.delta)
            print(event.data.delta, end="", flush=True)
        elif event.type == "run_item_stream_event" and event.name in ("tool_called", "tool_output"):
            print(f"\n[{event.name}] {event.item.raw_item}")
    print(f"\n\n[全部流式文本]\n{''.join(streamed)}")
    print(f"\n[最终回答]\n{result.final_output}")
    print(f"\n[本次运行生成的项目] {len(result.new_items)}")


if __name__ == "__main__":
    asyncio.run(main())
