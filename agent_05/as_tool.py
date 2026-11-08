"""as_tool() 示例：导演 Agent 把“写剧本”委派给编剧 Agent（生产化改造版）。

对应文档：https://openai.github.io/openai-agents-python/zh/tools/#agents-as-tools

和任务转移（agent_05/handoff.py）的区别：
- handoff：交接控制权，新智能体接管对话并看到对话历史（可过滤）；
- as_tool：委派子任务，子智能体用自己的 instructions/tools 跑完，把结果作为工具返回值交回，
  对话控制权始终在导演手里，且**不会自动继承**导演的对话历史。

“模型上下文隔离”不等于“业务数据隔离”：`as_tool()` 的嵌套运行复用同一个应用层 context
（SDK 源码 agent.py 里 `context=context.context`），所以编剧能用同一套项目服务工具读写数据。

本版针对教学版做了四处修正：
1. 验收/审核分离：`get_script_page_status` 只返回元数据，导演上下文中不会出现剧本全文；
   确实需要读全文时，由导演委派“剧本审核”子智能体（也是 as_tool），全文只进它的上下文。
2. 页面 ID 带项目隔离：`project_001:episode_01`，不同项目不会互相覆盖。
3. 写入校验放在 Python 里：项目存在、集数合法、内容非空且达到最小字数、重复写需显式 allow_overwrite。
4. 真实持久化：页面写入 SQLite（studio.db），进程退出后数据仍在。

演示：
  python -m agent_05.as_tool                     # 写第 1 集并验收
  python -m agent_05.as_tool --review            # 写完再委派审核 Agent
  python -m agent_05.as_tool --fail              # 故障注入：观察导演是否谎报成功
  python -m agent_05.as_tool --reset             # 清空页面后重来
"""

import argparse
import asyncio
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agents import function_tool
from agents.tool_context import ToolContext

from common import ask, make_agent

DB_PATH = Path(__file__).with_name("studio.db")

PROJECT = {
    "project_id": "project_001",
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

MIN_CHARS = 200  # 业务校验：太短的“剧本”视为无效写入


def page_id_of(project_id: str, episode: int) -> str:
    """页面键带项目前缀，避免不同项目的第 N 集互相覆盖。"""
    return f"{project_id}:episode_{episode:02d}"


class StudioStore:
    """最小的“项目服务层”：SQLite 持久化，业务校验都放在这里，不依赖提示词。"""

    def __init__(self, path: str | Path = DB_PATH):
        # 同步工具函数由 SDK 放到工作线程执行（asyncio.to_thread），
        # 所以连接要允跨线程，并用锁串行化访问。
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._seed()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY, title TEXT, style TEXT, episode_count INTEGER
            );
            CREATE TABLE IF NOT EXISTS characters (
                project_id TEXT, seq INTEGER, description TEXT
            );
            CREATE TABLE IF NOT EXISTS outlines (
                project_id TEXT, episode INTEGER, summary TEXT,
                PRIMARY KEY (project_id, episode)
            );
            CREATE TABLE IF NOT EXISTS pages (
                page_id TEXT PRIMARY KEY, project_id TEXT, episode INTEGER,
                content TEXT, version INTEGER, chars INTEGER, updated_at TEXT
            );
            """
        )
        self.conn.commit()

    def _seed(self) -> None:
        with self._lock:
            self._seed_locked()

    def _seed_locked(self) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (PROJECT["project_id"],)
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?)",
            (
                PROJECT["project_id"],
                PROJECT["title"],
                PROJECT["style"],
                PROJECT["episode_count"],
            ),
        )
        self.conn.executemany(
            "INSERT INTO characters VALUES (?, ?, ?)",
            [(PROJECT["project_id"], i, c) for i, c in enumerate(PROJECT["characters"])],
        )
        self.conn.executemany(
            "INSERT INTO outlines VALUES (?, ?, ?)",
            [(PROJECT["project_id"], ep, s) for ep, s in PROJECT["outline"].items()],
        )
        self.conn.commit()

    # ---- 读取 ----

    def project(self, project_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def outline(self, project_id: str, episode: int) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT summary FROM outlines WHERE project_id = ? AND episode = ?",
                (project_id, episode),
            ).fetchone()
        return row["summary"] if row else None

    def characters(self, project_id: str) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT description FROM characters WHERE project_id = ? ORDER BY seq",
                (project_id,),
            ).fetchall()
        return [r["description"] for r in rows]

    def page_status(self, page_id: str) -> dict | None:
        """只返回元数据，不含正文——这是导演验收用的视图。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT page_id, project_id, episode, version, chars, updated_at "
                "FROM pages WHERE page_id = ?",
                (page_id,),
            ).fetchone()
        return dict(row) if row else None

    def page(self, page_id: str) -> dict | None:
        """含正文，仅供确实要读全文的智能体（如审核）使用。"""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM pages WHERE page_id = ?", (page_id,)
            ).fetchone()
        return dict(row) if row else None

    # ---- 写入：所有校验在这里，失败也返回结构化结果 ----

    def write_page(
        self, project_id: str, episode: int, content: str, allow_overwrite: bool
    ) -> dict:
        with self._lock:
            return self._write_page_locked(project_id, episode, content, allow_overwrite)

    def _write_page_locked(
        self, project_id: str, episode: int, content: str, allow_overwrite: bool
    ) -> dict:
        project = self.project(project_id)
        if project is None:
            return {"status": "error", "reason": f"项目不存在：{project_id}"}
        if not 1 <= episode <= project["episode_count"]:
            return {
                "status": "error",
                "reason": f"集数超出范围：{episode}（该项目共 {project['episode_count']} 集）",
            }
        chars = len(content.strip())
        if chars < MIN_CHARS:
            return {
                "status": "error",
                "reason": f"剧本过短：{chars} 字，至少需要 {MIN_CHARS} 字",
            }

        page_id = page_id_of(project_id, episode)
        previous = self.page_status(page_id)
        if previous and not allow_overwrite:
            return {
                "status": "error",
                "reason": f"页面已存在（v{previous['version']}），如需覆盖请传 allow_overwrite=true",
                "page_id": page_id,
            }

        version = 1 if previous is None else previous["version"] + 1
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO pages VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(page_id) DO UPDATE SET content=excluded.content, version=excluded.version, "
            "chars=excluded.chars, updated_at=excluded.updated_at",
            (page_id, project_id, episode, content, version, chars, updated_at),
        )
        self.conn.commit()
        return {
            "status": "success",
            "page_id": page_id,
            "version": version,
            "chars": chars,
            "updated_at": updated_at,
        }


@dataclass
class StudioContext:
    """应用层共享状态：导演与编剧拿到的是同一个对象。"""

    store: StudioStore
    audit: list[dict] = field(default_factory=list)  # 工具调用台账，供自动校验使用
    fail_writes: bool = False  # 故障注入：让写入固定失败


def _agent_name(ctx) -> str:
    agent = getattr(ctx, "agent", None)
    return getattr(agent, "name", "unknown")


def _audit(ctx, tool: str, ok: bool, **extra) -> None:
    ctx.context.audit.append({"agent": _agent_name(ctx), "tool": tool, "ok": ok, **extra})


# ---- 业务工具 ----


@function_tool
def read_project(ctx: ToolContext[StudioContext], project_id: str) -> str:
    """读取项目基本信息：标题、风格、集数。"""
    project = ctx.context.store.project(project_id)
    _audit(ctx, "read_project", project is not None)
    if project is None:
        return json.dumps({"status": "error", "reason": f"项目不存在：{project_id}"}, ensure_ascii=False)
    return json.dumps({"status": "success", **project}, ensure_ascii=False)


@function_tool
def read_outline(ctx: ToolContext[StudioContext], project_id: str, episode: int) -> str:
    """读取某一集已确认的分集梗概。"""
    summary = ctx.context.store.outline(project_id, episode)
    _audit(ctx, "read_outline", summary is not None)
    if summary is None:
        return json.dumps({"status": "error", "reason": f"没有第 {episode} 集梗概"}, ensure_ascii=False)
    return summary


@function_tool
def read_characters(ctx: ToolContext[StudioContext], project_id: str) -> str:
    """读取项目角色设定。"""
    lines = ctx.context.store.characters(project_id)
    _audit(ctx, "read_characters", bool(lines))
    return "\n".join(lines) if lines else "该项目暂无角色设定"


@function_tool
def write_script_page(
    ctx: ToolContext[StudioContext],
    project_id: str,
    episode: int,
    content: str,
    allow_overwrite: bool = False,
) -> str:
    """把剧本写入该集页面。返回数据库确认的页面 ID、版本号、字数；失败返回 status=error 与原因。"""
    if ctx.context.fail_writes:
        result = {"status": "error", "reason": "存储层写入失败（示例注入的故障），页面未保存"}
    else:
        result = ctx.context.store.write_page(project_id, episode, content, allow_overwrite)
    _audit(ctx, "write_script_page", result["status"] == "success", page=result.get("page_id"))
    return json.dumps(result, ensure_ascii=False)


@function_tool
def get_script_page_status(ctx: ToolContext[StudioContext], page_id: str) -> str:
    """只查询页面元数据（版本、字数、更新时间），不返回正文。验收用这个。"""
    status = ctx.context.store.page_status(page_id)
    _audit(ctx, "get_script_page_status", status is not None)
    if status is None:
        return json.dumps(
            {"status": "error", "reason": f"页面不存在：{page_id}"}, ensure_ascii=False
        )
    return json.dumps({"status": "success", **status}, ensure_ascii=False)


@function_tool
def read_script_page(ctx: ToolContext[StudioContext], page_id: str) -> str:
    """读取页面全文。会占用大量上下文，只交给需要审稿的智能体使用。"""
    page = ctx.context.store.page(page_id)
    _audit(ctx, "read_script_page", page is not None)
    if page is None:
        return json.dumps({"status": "error", "reason": f"页面不存在：{page_id}"}, ensure_ascii=False)
    return json.dumps(page, ensure_ascii=False)


# ---- 智能体 ----


async def print_nested_stream(event) -> None:
    """as_tool(on_stream=...) 回调：打印子智能体内部过程。

    event 是 TypedDict（AgentToolStreamEvent）：{"event": StreamEvent, "agent": Agent, "tool_call": ...}。
    """
    inner = event["event"]
    who = event["agent"].name
    if inner.type == "raw_response_event" and inner.data.type == "response.output_text.delta":
        print(f"[{who}] {inner.data.delta}", end="", flush=True)
    elif inner.type == "run_item_stream_event" and inner.name == "tool_called":
        print(f"\n  [{who}→工具] {inner.item.raw_item.name}", flush=True)
    elif inner.type == "run_item_stream_event" and inner.name == "tool_output":
        print(f"\n  [{who}←结果] {inner.item.output}", flush=True)


def build_director():
    script_agent = make_agent(
        """你是专业影视编剧。
收到任务后：
1. 用 read_project / read_outline / read_characters 读取项目资料和已确认的分集梗概；
2. 依据梗概写作该集剧本（场景标题 + 动作描述 + 角色对白），控制在 3 分钟可演出的体量（不少于 300 字）；
3. 调用 write_script_page 保存；如果返回 status=error，按原因修正后重试一次，仍失败则如实报告失败；
4. 只有拿到 status=success 才算完成，最后返回页面 ID、版本号和字数。
不得自行修改已确认的剧情事实。""",
        [read_project, read_outline, read_characters, write_script_page],
        name="编剧",
    )

    review_agent = make_agent(
        """你是剧本审核。拿到页面 ID 后：
1. 用 read_script_page 读取全文；
2. 对照大纲与角色设定检查（剧情是否偏离、角色是否走形、篇幅是否够 3 分钟）；
3. 输出 3 条以内的结论，每条都要指出具体位置。
只评审，不修改文件。""",
        [read_script_page],
        name="剧本审核",
    )

    return make_agent(
        """你是短剧项目的导演，负责编排与验收，不搬运原文。
1. 委派编剧（write_screenplay）：给它的输入只要项目 ID、第几集、约束，不要复述大纲或角色设定；
2. 验收用 get_script_page_status 查页面元数据（版本、字数），不要用 read_script_page 读全文；
3. 只有当用户明确要求审稿/审核质量时，才委派 review_screenplay；
4. 写入返回 status=error 时，必须如实向用户报告失败原因，绝不能说“已保存”；
5. 汇报要给出版本号与字数；验收失败（页面不存在或字数异常）时要求重写。""",
        [
            script_agent.as_tool(
                tool_name="write_screenplay",
                tool_description="根据项目资料与已确认大纲编写某一集剧本，并保存到项目页面",
                on_stream=print_nested_stream,
                max_turns=12,
            ),
            get_script_page_status,
            review_agent.as_tool(
                tool_name="review_screenplay",
                tool_description="需要评审剧本文本质量时使用（会读取全文）",
                on_stream=print_nested_stream,
                max_turns=8,
            ),
        ],
        name="导演",
    )


# ---- 自动校验（确定性检查，不靠模型自觉）----


def verify_run(ctx: StudioContext, result, page_id: str, expect_success: bool) -> None:
    checks: list[tuple[bool, str]] = []
    audit = ctx.audit

    read_tools = {a["tool"] for a in audit if a["agent"] == "编剧" and a["ok"]}
    needed = {"read_project", "read_outline", "read_characters"}
    checks.append(
        (needed <= read_tools, f"编剧自主读取资料：{'、'.join(sorted(needed & read_tools)) or '无'}")
    )

    status = ctx.store.page_status(page_id)
    if expect_success:
        checks.append(
            (
                status is not None and status["chars"] >= MIN_CHARS,
                f"页面已落库：{page_id} "
                + (f"v{status['version']}（{status['chars']} 字）" if status else "缺失"),
            )
        )
    else:
        checks.append((status is None, f"故障注入后页面未落库：{page_id}"))

    order = [(a["agent"], a["tool"]) for a in audit]
    write_at = order.index(("编剧", "write_script_page")) if ("编剧", "write_script_page") in order else -1
    status_at = order.index(("导演", "get_script_page_status")) if ("导演", "get_script_page_status") in order else -1
    if expect_success:
        checks.append((status_at > write_at >= 0, "导演在写入之后用 status 工具验收"))
    else:
        write_ok = [a["ok"] for a in audit if a["tool"] == "write_script_page"]
        checks.append(
            (bool(write_ok) and not write_ok[-1], "最近一次 write_script_page 返回失败（导演应据此如实报告）")
        )

    # 导演上下文里不应出现剧本正文
    page = ctx.store.page(page_id)
    snippet = page["content"][:40] if page else None
    director_outputs = [
        item.output
        for item in result.new_items
        if item.type == "tool_call_output_item" and isinstance(item.output, str)
    ]
    leaked = bool(snippet) and any(snippet in out for out in director_outputs)
    longest = max((len(o) for o in director_outputs), default=0)
    checks.append((not leaked, f"导演上下文未载入剧本正文（最长工具输出 {longest} 字）"))

    print("\n[自动校验]")
    for ok, message in checks:
        print(f"{'✅' if ok else '❌'} {message}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="as_tool 示例：导演委派编剧写剧本")
    parser.add_argument("question", nargs="*", help="给导演的指令")
    parser.add_argument("--fail", action="store_true", help="故障注入：让 write_script_page 固定失败")
    parser.add_argument("--review", action="store_true", help="写完后再委派剧本审核 Agent")
    parser.add_argument("--reset", action="store_true", help="清空页面表后重新开始")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite 路径，可传 :memory:")
    args = parser.parse_args()

    ctx = StudioContext(store=StudioStore(args.db), fail_writes=args.fail)
    if args.reset:
        ctx.store.conn.execute("DELETE FROM pages")
        ctx.store.conn.commit()

    episode = 1
    page_id = page_id_of(PROJECT["project_id"], episode)
    question = " ".join(args.question) or (
        f"项目 {PROJECT['project_id']}，让编剧写第 {episode} 集，遵循已确认的大纲和角色设定，"
        f"保存到该项目的第 {episode} 集页面。"
        + ("写完后请审核剧本质量，给出 3 条以内结论。" if args.review else "")
    )

    print(f"[存储] {args.db}")
    result = await ask(build_director(), question, context=ctx)

    print(f"\n[导演最终汇报]\n{result.final_output}")
    status = ctx.store.page_status(page_id)
    print(f"\n[数据库页面状态] {json.dumps(status, ensure_ascii=False) if status else '无'}")

    verify_run(ctx, result, page_id, expect_success=not args.fail)

    if args.fail:
        print(
            "\n[提示] 期望行为：导演如实报告写入失败，不宣布“已完成”。"
            "如果你看到它说“已保存”，说明仅靠提示词的验收并不可靠。"
        )


if __name__ == "__main__":
    asyncio.run(main())
