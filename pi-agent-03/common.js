// 03 课的公共代码：模型、工具、agent 工厂、打印工具
import { Agent } from "@earendil-works/pi-agent-core";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { Type } from "typebox";

export const model = {
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// get_time 工具；delayMs 用来人为拖慢执行，给 steer 留出"工具运行中"的时间窗口
export function makeGetTimeTool({ delayMs = 0 } = {}) {
  return {
    name: "get_time",
    label: "Get Time",
    description: "获取当前日期和时间。可指定 IANA 时区（如 Asia/Tokyo、America/New_York），不指定则用本机时区。",
    parameters: Type.Object({
      timezone: Type.Optional(Type.String({ description: "IANA 时区名" })),
    }),
    execute: async (toolCallId, params) => {
      if (delayMs) await sleep(delayMs);
      const timeZone = params.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
      const text = new Intl.DateTimeFormat("zh-CN", { timeZone, dateStyle: "full", timeStyle: "long" }).format(new Date());
      return { content: [{ type: "text", text: `${timeZone} 当前时间：${text}` }], details: { timeZone } };
    },
  };
}

export function makeAgent({ systemPrompt, tools = [] }) {
  const agent = new Agent({
    initialState: {
      systemPrompt,
      model,
      thinkingLevel: process.env.PI_THINKING ?? "low",
    },
    streamFn: (m, context, options) => streamSimple(m, context, { ...options, apiKey }),
  });
  agent.state.tools = tools;
  return agent;
}

// 终端打印：turn 标记、正文流式输出、工具调用（不打印思考，保持输出简洁）
export function attachPrinter(agent) {
  agent.subscribe((event) => {
    if (event.type === "turn_start") process.stdout.write("\n\x1b[36m[turn]\x1b[0m ");
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      process.stdout.write(event.assistantMessageEvent.delta);
    }
    if (event.type === "tool_execution_start") {
      console.log(`\n\x1b[33m[tool 开始] ${event.toolName}\x1b[0m ${JSON.stringify(event.args)}`);
    }
    if (event.type === "tool_execution_end") {
      console.log(`\x1b[33m[tool 结束] ${event.toolName} isError=${event.isError}\x1b[0m`);
    }
  });
}

export const section = (title) => console.log(`\n\x1b[35m${"=".repeat(8)} ${title} ${"=".repeat(8)}\x1b[0m`);

export async function ask(agent, question) {
  console.log(`\n\x1b[32m> ${question}\x1b[0m`);
  await agent.prompt(question);
  console.log();
}

// 把 agent.state.messages 缩成一行一条，看清"记忆"里到底存了什么
// 消息的 content 可能是字符串，也可能是内容块数组；块的类型名我没全部核实，所以直接打印类型
export function printMessages(messages, title = "messages") {
  console.log(`\n\x1b[90m--- ${title}（共 ${messages.length} 条）---`);
  messages.forEach((m, i) => {
    let preview;
    if (typeof m.content === "string") {
      preview = m.content;
    } else if (Array.isArray(m.content)) {
      preview = m.content
        .map((b) => (b.type === "text" ? `text:${b.text}` : b.type === "thinking" ? "thinking:…" : `${b.type}:${JSON.stringify(b).slice(0, 60)}`))
        .join(" | ");
    } else {
      preview = "(无 content)";
    }
    console.log(`#${i} ${m.role.padEnd(10)} ${preview.replace(/\s+/g, " ").slice(0, 90)}`);
  });
  console.log("\x1b[0m");
}
