import asyncio

from agents import RunConfig, SQLiteSession
from agents.run import ModelInputData

from common import ask, make_agent, make_get_time, print_messages


async def main():
    pending = []

    def on_tool_start():
        if not pending:
            pending.append("改主意了：只保留东京的结果，纽约和伦敦忽略。回答控制在一句话。")

    def inject(data):
        items = list(data.model_data.input)
        if pending:
            # 每次后续模型调用都加入指令；这只改变模型输入，不写入会话。
            items.append({"role": "user", "content": pending[0]})
            print("\n[已向模型输入加入改指令]")
        return ModelInputData(input=items, instructions=data.model_data.instructions)

    agent = make_agent("需要时间信息时调用 get_time，用中文回答。", [make_get_time(2, on_tool_start)])
    session = SQLiteSession("steer")
    await ask(agent, "查一下东京、纽约、伦敦现在几点。", session, RunConfig(call_model_input_filter=inject))
    await ask(agent, "最后再用英文把结论重复一遍。", session)
    await print_messages(session, "最终会话记录")


if __name__ == "__main__":
    asyncio.run(main())
