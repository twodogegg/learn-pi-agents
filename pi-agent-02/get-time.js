import { Agent } from "@earendil-works/pi-agent-core";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";
import { Type } from "typebox";

// 1. 模型：和 pi-agent-01 保持一致
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

// 2. 定义工具 get_time
//    - description 是写给 LLM 看的：它靠这段话决定"什么时候该调用我"
//    - parameters 用 typebox 描述，timezone 是可选参数
//    - execute 返回 { content, details }：content 给 LLM，details 留给你自己的 UI/日志
const getTimeTool = {
  name: "get_time",
  label: "Get Time",
//   executionMode: "sequential",  串行执行
  description:
    "获取当前的日期和时间。可以指定 IANA 时区（如 Asia/Tokyo、America/Tijuana）；不指定则使用本机时区。",
  parameters: Type.Object({
    timezone: Type.Optional(
      Type.String({ description: "IANA 时区名，例如 Asia/Shanghai。不填则用本机时区。" }),
    ),
  }),
  execute: async (toolCallId, params) => {
    const now = new Date();
    const timeZone = params.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;

    // 时区名不合法时，Intl 会抛 RangeError。这里不 catch，
    // 框架会把异常以 isError: true 回报给 LLM（第 5 步实验会用到）
    const text = new Intl.DateTimeFormat("zh-CN", {
      timeZone,
      dateStyle: "full",
      timeStyle: "long",
    }).format(now);

    return {
      content: [{ type: "text", text: `${timeZone} 当前时间：${text}` }],
      details: { timeZone, iso: now.toISOString() },
    };
  },
};

// 3. 创建 agent，并把工具挂到 state.tools 上
const agent = new Agent({
  initialState: {
    systemPrompt: "You are a helpful assistant. 需要时间信息时，必须调用 get_time 工具，不要猜。",
    model,
    thinkingLevel: process.env.PI_THINKING ?? "low",
  },
  streamFn: (m, context, options) => streamSimple(m, context, { ...options, apiKey }),
});
agent.state.tools = [getTimeTool];

// 4. 订阅事件：除了文本，再把"一轮 / 工具执行"的过程打出来
agent.subscribe((event) => {
  if (event.type === "turn_start") console.log("\n\x1b[36m--- turn_start ---\x1b[0m");
  if (event.type === "turn_end") console.log("\n\x1b[36m--- turn_end ---\x1b[0m");

  if (event.type === "message_update") {
    const e = event.assistantMessageEvent;
    if (e.type === "thinking_start") process.stdout.write("\x1b[90m[思考] ");
    if (e.type === "thinking_delta") process.stdout.write(e.delta);
    if (e.type === "thinking_end") process.stdout.write("\x1b[0m\n");
    if (e.type === "text_delta") process.stdout.write(e.delta);
  }

  // 工具事件的字段名我没有逐一核实，所以先整体打印，跑一遍看清结构后再精简
  if (event.type === "tool_execution_start" || event.type === "tool_execution_end") {
    console.log(`\n\x1b[33m[${event.type}]\x1b[0m`, JSON.stringify(event, null, 2));
  }

  if (event.type === "agent_end") {
    const last = event.messages.at(-1);
    if (last?.usage) {
      process.stdout.write(`\n\n[usage] in=${last.usage.input} out=${last.usage.output}\n`);
    }
  }
});

// 5. 发一个必须靠工具才能答对的问题
await agent.prompt(process.argv[2] ?? "查一下 Mars/Base 的时间");