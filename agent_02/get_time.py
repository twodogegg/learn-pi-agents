import asyncio
import sys

from common import ask, make_agent, make_get_time


async def main():
    agent = make_agent("需要时间信息时必须调用 get_time，不要猜。", [make_get_time()])
    question = sys.argv[1] if len(sys.argv) > 1 else "查一下 Mars/Base 的时间"
    result = await ask(agent, question)
    print(f"\n[usage] {result.context_wrapper.usage}")


if __name__ == "__main__":
    asyncio.run(main())
