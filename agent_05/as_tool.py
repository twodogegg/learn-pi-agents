"""as_tool() 示例：导演 Agent 把“写剧本”委派给编剧 Agent。

对应文档：https://openai.github.io/openai-agents-python/zh/tools/#agents-as-tools

和任务转移（agent_05/handoff.py）的区别：
- handoff：交接控制权，新智能体接管对话并看到对话历史（可过滤）；
- as_tool：委派子任务，子智能体用自己的 instructions/tools 跑完，把结果作为工具返回值交回，
  对话控制权始终在导演手里，且**不会自动继承**导演的对话历史。

但“模型上下文”隔离不等于“业务数据”隔离：
`as_tool()` 的嵌套运行复用同一个应用层 context（见 SDK 源码 agent.py 里的 `context=context.context`），
所以编剧能用同一套项目服务工具去读大纲、写页面。

本示例还演示两条工程原则：
1. 导演不搬运原文，只给标识（project_id / episode），资料由编剧自己用工具读；
2. 保存结果以“数据库返回值”为准，导演再调 read_script_page 复核，而不是听编剧说“已保存”。
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field

from agents import RunContextWrapper, function_tool

from common import ask, make_agent

PROJECT_ID = "project_001"

# 演示用的“项目数据库”，真实项目里换成数据库 / API 客户端。
PROJECTS = {
    PROJECT_ID: {
        "title": "深夜便利店",
        "style": "都市温情竖屏短剧，单集 3 分钟",
        "episode_count": 3,
        "characters": [
            "林夏：28 岁便利店店员，寡言、心软，习惯替别人着想",
            "周牧：32 岁常客兼程序员，长期失眠，嘴硬但怕麻烦别人",
        ],
        "outline": {
            1: "深夜值班的林夏遇到醉酒的周牧，两人第一次真正对话，结尾留下“明天还来吗”的悬念。",
            2: "周牧连着三晚来买同一种关东煮，林夏发现他在躲家里的事，两人交换了各自的失眠理由。",
            3: "便利店要拆迁，林夏准备辞职；周牧用一晚上的时间把店里的监控剪成短片，向她告白。",
        },
    }
}


@dataclass
class StudioContext:
    """应用层共享状态：所有智能体拿到的是同一个对象。"""

    projects: dict = field(default_factory=lambda: PROJECTS)
    pages: dict = field(default_factory=dict)  # 页面存储：page_id -> {content, version, ...}

    def page_id(self, episode: int) -> str:
        return f"episode_{episode:02d}"


# ---- 业务工具：编剧和导演都能用（靠同一个 context 拿到项目数据）----


@function_tool
def read_project(ctx: RunContextWrapper[StudioContext], project_id: str) -> str:
    """读取项目基本信息：标题、风格、集数。"""
    project = ctx.context.projects.get(project_id)
    if not project:
        raise ValueError(f"项目不存在：{project_id}")
    return json.dumps(
        {
            "project_id": project_id,
            "title": project["title"],
            "style": project["style"],
            "episode_count": project["episode_count"],
        },
        ensure_ascii=False,
    )


@function_tool
def read_outline(ctx: RunContextWrapper[StudioContext], project_id: str, episode: int) -> str:
    """读取某一集已确认的分集梗概。"""
    project = ctx.context.projects[project_id]
    return project["outline"].get(episode, "该集暂无梗概")


@function_tool
def read_characters(ctx: RunContextWrapper[StudioContext], project_id: str) -> str:
    """读取项目角色设定。"""
    return "\n".join(ctx.context.projects[project_id]["characters"])


@function_tool
def write_script_page(
    ctx: RunContextWrapper[StudioContext], project_id: str, episode: int, content: str
) -> str:
    """把剧本写入该集对应页面，返回数据库确认的页面 ID、版本号和字数。"""
    page_id = ctx.context.page_id(episode)
    previous = ctx.context.pages.get(page_id)
    version = 1 if previous is None else previous["version"] + 1
    ctx.context.pages[page_id] = {
        "project_id": project_id,
        "episode": episode,
        "content": content,
        "version": version,
        "chars": len(content),
    }
    # 只返回存储层确认过的结果，避免智能体“口头说已保存”。
    return json.dumps(
        {
            "status": "success",
            "project_id": project_id,
            "page_id": page_id,
            "version": version,
            "chars": len(content),
        },
        ensure_ascii=False,
    )


@function_tool
def read_script_page(ctx: RunContextWrapper[StudioContext], page_id: str) -> str:
    """读取已保存的剧本页面（用于复核是否真的写入成功）。"""
    page = ctx.context.pages.get(page_id)
    if not page:
        return f"页面不存在：{page_id}"
    return json.dumps(page, ensure_ascii=False)


# ---- 智能体 ----


async def print_nested_stream(event) -> None:
    """as_tool(on_stream=...) 回调：把编剧内部的过程也打印出来。

    event 是 TypedDict（AgentToolStreamEvent）：{"event": StreamEvent, "agent": Agent, "tool_call": ...}。
    """
    inner = event["event"]
    if inner.type == "raw_response_event" and inner.data.type == "response.output_text.delta":
        print(inner.data.delta, end="", flush=True)
    elif inner.type == "run_item_stream_event" and inner.name == "tool_called":
        print(f"\n  [编剧调用工具] {inner.item.raw_item.name}", flush=True)
    elif inner.type == "run_item_stream_event" and inner.name == "tool_output":
        print(f"\n  [编剧得到结果] {inner.item.output}", flush=True)


def build_director():
    # 编剧：自己的 instructions + 自己的工具，不继承导演的对话历史
    script_agent = make_agent(
        """你是专业影视编剧。
收到任务后：
1. 用 read_project / read_outline / read_characters 读取项目资料和已确认的分集梗概；
2. 依据梗概写作该集剧本（场景标题 + 动作描述 + 角色对白），控制在 3 分钟可演出的体量；
3. 调用 write_script_page 保存到该集页面；
4. 只有拿到 write_script_page 返回的 success 后才算完成，最后返回页面 ID、版本号和字数。
不得自行修改已确认的剧情事实。""",
        [read_project, read_outline, read_characters, write_script_page],
        name="编剧",
    )

    # 导演：只负责编排、验收、汇报，不搬运原文
    return make_agent(
        """你是短剧项目的导演，负责管理和验收。
把剧本编写任务委派给编剧：给它的输入只要包含项目 ID、第几集、目标页面和约束，
不要把大纲或角色设定原文复述给它——它自己会用工具读。用户已经给出项目 ID 与集数时直接开始，不要反问。
编剧返回后，必须调用 read_script_page 复核页面确实存在且字数合理，再向用户汇报；
汇报里要包含页面 ID 与版本号；如果复核失败，说明原因并要求重写。""",
        [
            script_agent.as_tool(
                tool_name="write_screenplay",
                tool_description="根据项目资料与已确认大纲编写某一集剧本，并保存到项目页面",
                on_stream=print_nested_stream,
                max_turns=12,
            ),
            read_script_page,
        ],
        name="导演",
    )


async def main():
    question = (
        sys.argv[1]
        if len(sys.argv) > 1
        else f"项目 {PROJECT_ID}，让编剧写第 1 集，遵循已确认的大纲和角色设定，存到 episode_01 页面。"
    )
    context = StudioContext()  # 导演与编剧共享的业务上下文

    ask_result = await ask(build_director(), question, context=context)

    print(f"\n[导演最终汇报]\n{ask_result.final_output}")
    print("\n[项目服务里实际存在的页面]")
    for page_id, page in context.pages.items():
        print(f"- {page_id} v{page['version']}（{page['chars']} 字）")
    if not context.pages:
        print("- 没有写入任何页面")

    # 导演的对话里没有出现大纲原文，只有工具读写的结果；编剧的上下文则完全独立。
    print(f"\n[导演本轮生成的项目数] {len(ask_result.new_items)}")


if __name__ == "__main__":
    asyncio.run(main())
