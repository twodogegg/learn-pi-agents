import asyncio
import os
from datetime import datetime, timedelta, timezone as utc_timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel, Runner, function_tool, set_tracing_disabled
from openai import DefaultAsyncHttpxClient


def make_agent(instructions, tools=None, **kwargs):
    # 保留原项目的 Chat Completions 网关配置。
    base_url = os.getenv("PI_BASE_URL", "http://127.0.0.1:3425/v1")
    local = urlparse(base_url).hostname in {"127.0.0.1", "localhost", "::1"}
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=os.getenv("PI_API_KEY", "magpie"),
        http_client=DefaultAsyncHttpxClient(trust_env=False) if local else None,
    )
    set_tracing_disabled(True)
    return Agent(
        name="时间助手",
        instructions=instructions,
        model=OpenAIChatCompletionsModel(
            model=os.getenv("PI_MODEL", "auto/auto"), openai_client=client
        ),
        tools=tools or [],
        **kwargs,
    )


def make_get_time(delay=0, on_start=None):
    @function_tool
    async def get_time(timezone: str | None = None) -> str:
        """获取当前时间和 ISO 时间戳。timezone 为 IANA 时区名，不填使用本机时区。"""
        if on_start:
            on_start()
        if delay:
            await asyncio.sleep(delay)
        zone = ZoneInfo(timezone) if timezone else datetime.now().astimezone().tzinfo
        now = datetime.now(utc_timezone.utc)
        return f"{timezone or '本地时区'}：{now.astimezone(zone).isoformat()}（iso={now.isoformat()}）"

    return get_time


@function_tool
def add_hours(iso: str, hours: float, timezone: str | None = None) -> str:
    """在 ISO 时间戳上加减小时，timezone 为展示结果的 IANA 时区名。"""
    start = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("iso 必须包含时区偏移")
    zone = ZoneInfo(timezone) if timezone else datetime.now().astimezone().tzinfo
    return f"{timezone or '本地时区'}：{(start + timedelta(hours=hours)).astimezone(zone).isoformat()}"


async def ask(agent, question, session=None, run_config=None):
    print(f"\n> {question}")
    result = Runner.run_streamed(agent, question, session=session, run_config=run_config)
    async for event in result.stream_events():
        if event.type == "raw_response_event" and event.data.type == "response.output_text.delta":
            print(event.data.delta, end="", flush=True)
        elif event.type == "run_item_stream_event" and event.name == "tool_called":
            print(f"\n[工具调用] {event.item.raw_item}")
        elif event.type == "run_item_stream_event" and event.name == "tool_output":
            print(f"\n[工具结果] {event.item.output}")
    print()
    return result


async def print_messages(session, title):
    items = await session.get_items()
    print(f"\n--- {title}（共 {len(items)} 条）---")
    for index, item in enumerate(items):
        print(f"#{index} {item}")
