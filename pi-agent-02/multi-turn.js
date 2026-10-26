import { Agent } from "@earendil-works/pi-agent-core";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { Type } from "typebox";

const model = {
  id: "auto/auto",
  name: "Auto",
  api: "openai-completions",
  provider: "magpie",
  baseUrl: process.env.PI_BASE_URL ?? "http://127.0.0.1:3425/v1",
  input: ["text"],
  cost: { input: 2.0, output: 8.0, cacheRead: 0.2, cacheWrite: 2.5 },
  reasoning: true,
  thinkingLevelMap: { low: "low", high: "high", max: "max", minimal: null, medium: null, off: null },
  contextWindow: 256000,
  maxTokens: 4096,
};
const apiKey = process.env.PI_API_KEY ?? "magpie";

// ---- 工具 1：get_time（和 get-time.js 一致）----
const getTimeTool = {
  name: "get_time",
  label: "Get Time",
  description: "获取当前的日期和时间，返回可读时间和 ISO 时间戳。可指定 IANA 时区，不指定则用本机时区。",
  parameters: Type.Object({
    timezone: Type.Optional(Type.String({ description: "IANA 时区名，例如 Asia/Tokyo" })),
  }),
  execute: async (toolCallId, params) => {
    const now = new Date();
    const timeZone = params.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    const text = new Intl.DateTimeFormat("zh-CN", { timeZone, dateStyle: "full", timeStyle: "long" }).format(now);
    return {
      content: [{ type: "text", text: `${timeZone} 当前时间：${text}（iso=${now.toISOString()}）` }],
      details: { timeZone, iso: now.toISOString() },
    };
  },
};

// ---- 工具 2：add_hours ----
// 它需要 get_time 返回的 iso 作为输入，所以模型无法和 get_time 并行调用，
// 只能先调 get_time、拿到结果、再调 add_hours —— 这就制造出多个 turn
const addHoursTool = {
  name: "add_hours",
  label: "Add Hours",
  description: "在给定的 ISO 时间戳上加减若干小时，返回目标时区下的可读时间。做时间加减必须用这个工具。",
  parameters: Type.Object({
    iso: Type.String({ description: "起始时间的 ISO 字符串，来自 get_time" }),
    hours: Type.Number({ description: "要加的小时数，可为负" }),
    timezone: Type.Optional(Type.String({ description: "展示结果用的 IANA 时区" })),
  }),
  execute: async (toolCallId, params) => {
    const target = new Date(new Date(params.iso).getTime() + params.hours * 3600_000);
    const timeZone = params.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
    const text = new Intl.DateTimeFormat("zh-CN", { timeZone, dateStyle: "full", timeStyle: "long" }).format(target);
    return { content: [{ type: "text", text: `${timeZone}：${text}` }], details: { iso: target.toISOString() } };
  },
};

const agent = new Agent({
  initialState: {
    // 关键：要求每次调用工具前先说一句话 —— 保证每个 turn 都有 text_delta
    systemPrompt:
      "You are a helpful assistant. 需要时间信息时必须调用 get_time；做时间加减必须调用 add_hours。" +
      "每次调用工具之前，先用一句话说明你要做什么。",
    model,
    thinkingLevel: process.env.PI_THINKING ?? "low",
  },
  streamFn: (m, context, options) => streamSimple(m, context, { ...options, apiKey }),
});
agent.state.tools = [getTimeTool, addHoursTool];

// ---- 记录：按 turn 分段累积 text_delta ----
const streamedByTurn = []; // streamedByTurn[i] = 第 i 个 turn 流式收到的全部文本
let turnIndex = -1;

// 兼容 content 是字符串或 [{type:"text", text}] 数组两种写法（字段结构我没核实）
const textOf = (msg) => {
  if (!msg) return "";
  if (typeof msg.content === "string") return msg.content;
  if (Array.isArray(msg.content)) {
    return msg.content.filter((b) => b.type === "text").map((b) => b.text).join("");
  }
  return "";
};

agent.subscribe((event) => {
  if (event.type === "turn_start") {
    turnIndex += 1;
    streamedByTurn[turnIndex] = "";
    console.log(`\n\x1b[36m=== turn ${turnIndex} 开始 ===\x1b[0m`);
  }

  if (event.type === "message_update") {
    const e = event.assistantMessageEvent;
    if (e.type === "text_delta") {
      streamedByTurn[turnIndex] += e.delta;
      process.stdout.write(e.delta); // 和你之前一样：实时打到终端
    }
  }

  if (event.type === "tool_execution_start") {
    console.log(`\n\x1b[33m[tool] ${event.toolName}\x1b[0m`, JSON.stringify(event.args));
  }

  if (event.type === "agent_end") {
    const last = event.messages.at(-1);
    const streamedAll = streamedByTurn.join("");
    const finalText = textOf(last);

    console.log("\n\n\x1b[35m================ 对比 ================\x1b[0m");
    console.log("消息角色序列：", event.messages.map((m) => m.role).join(" → "));
    streamedByTurn.forEach((t, i) => console.log(`\n[turn ${i} 流式文本]\n${t || "(空)"}`));
    console.log("\n[agent_end 最后一条消息文本]\n" + (finalText || "(空)"));
    console.log(
      `\n流式累计 ${streamedAll.length} 字 vs 最后一条 ${finalText.length} 字 → ` +
        (streamedAll === finalText ? "一致" : "\x1b[31m不一致\x1b[0m"),
    );
  }
});

await agent.prompt(process.argv[2] ?? "先查一下 Mars/Base 的时间，然后告诉我 3 小时后东京是几点。");