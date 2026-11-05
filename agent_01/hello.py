import asyncio

from common import ask, make_agent


async def main():
    agent = make_agent("You are a helpful assistant.")
    result = await ask(agent, "现在时间几点了")
    print(f"\n[最终回答]\n{result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
