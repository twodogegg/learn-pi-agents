import asyncio

from agents import SQLiteSession

from common import ask, make_agent, make_get_time, print_messages


async def main():
    agent = make_agent("需要时间信息时必须调用 get_time。用中文简短回答。", [make_get_time()])
    session = SQLiteSession("lesson")
    print("\n=== A. 同一个会话连续提问 ===")
    await ask(agent, "东京现在几点？", session)
    await print_messages(session, "第 1 问之后")
    await ask(agent, "那纽约呢？", session)
    await print_messages(session, "第 2 问之后")
    print("\n=== B. 全新会话 ===")
    await ask(agent, "那纽约呢？", SQLiteSession("fresh"))
    print("\n=== C. 清空会话 ===")
    await session.clear_session()
    await ask(agent, "我刚才问过你什么？", session)
    await print_messages(session, "清空后")


if __name__ == "__main__":
    asyncio.run(main())
