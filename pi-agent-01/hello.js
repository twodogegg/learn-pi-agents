import { Agent } from "@earendil-works/pi-agent-core";
import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";

// 1. 描述一个模型（这里用本机 magpie 网关，OpenAI 兼容接口）
const model = {
  id: "auto/auto",
  name: "Auto",
  api: "openai-completions",
  provider: "magpie",
  baseUrl: process.env.PI_BASE_URL ?? "http://127.0.0.1:3425/v1",
  input: ["text"],
  cost: {
    input: 2.00,
    output: 8.00,
    cacheRead: 0.20,
    cacheWrite: 2.50,
  },
  // 声明这是思考模型，并告诉 pi：pi 的等级名 → 该网关认识的等级名
  reasoning: true,
  thinkingLevelMap: { low: "low", high: "high", max: "max", minimal: null, medium: null, off: null },
  contextWindow: 256000,
  maxTokens: 4096,
};

const apiKey = process.env.PI_API_KEY ?? "magpie";

// 2. 创建 agent
const agent = new Agent({
  initialState: {
    systemPrompt: "You are a helpful assistant.",
    model,
    // 思考等级：off | minimal | low | medium | high | xhigh | max
    thinkingLevel: process.env.PI_THINKING ?? "high",
  },
  streamFn: (m, context, options) => streamSimple(m, context, { ...options, apiKey }),
});

// 3. 订阅事件，把流式文本打到终端
agent.subscribe((event) => {
  if (event.type === "message_update") {
    const e = event.assistantMessageEvent;
    if (e.type === "thinking_start") process.stdout.write("\x1b[90m[思考] ");
    if (e.type === "thinking_delta") process.stdout.write(e.delta);
    if (e.type === "thinking_end") process.stdout.write("\x1b[0m\n");
    if (e.type === "text_delta") process.stdout.write(e.delta);
  }
  if (event.type === "agent_end") {
    const last = event.messages.at(-1);
    console.log(last.usage.cost);
    if (last?.usage) {
      process.stdout.write(
        `\n\n[usage] in=${last.usage.input} out=${last.usage.output} ` +
          `cacheRead=${last.usage.cacheRead ?? 0} reasoning=${last.usage.reasoning ?? 0}\n`,
      );
    }
  }
  
  
});

// 4. 发一句话
await agent.prompt("9.11 和 9.9 哪个大？");
