import asyncio

from common import ask, make_agent, make_get_time


async def main():
    agent = make_agent(
        "你是时间助手，查询时间必须调用 get_time。",
        [make_get_time()],
        tool_use_behavior="stop_on_first_tool",
    )
    result = await ask(agent, "现在几点？")
    print(f"\n[工具结果作为最终输出]\n{result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
