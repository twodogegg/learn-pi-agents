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
    maxTokens: 1024,
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

  // 1. 处理模型流式输出
  if (event.type === "message_update") {
    const e = event.assistantMessageEvent;

    // 模型思考：仅内部调试
    if (e.type === "thinking_delta") {
      process.stderr.write(e.delta);
    }

    // 普通文本：暂时作为预览
    if (e.type === "text_delta") {
      process.stdout.write(e.delta);
    }

    // 模型开始生成工具调用
    if (e.type === "toolcall_start") {
      console.log("\n[正在准备调用工具]");
    }
  }

  // 2. 整个 Agent Run 结束
  if (event.type === "agent_end") {
    // 从本次运行的消息里找最后一条 Assistant 消息
    const lastAssistant = [...event.messages]
      .reverse()
      .find(m => m.role === "assistant");

    // 检查是否正常完成
    if (lastAssistant?.stopReason !== "stop") {
      console.log("\n[任务未正常完成]");
      return;
    }

    // 只提取 text，排除 thinking 和 toolCall
    const finalText = lastAssistant.content
      .filter(block => block.type === "text")
      .map(block => block.text)
      .join("\n")
      .trim();

    if (!finalText) {
      console.log("\n[没有最终文本回复]");
      return;
    }

    console.log("\n\n[最终回答]");
    console.log(finalText);

    // 这里才把 finalText 交给客服消息发送服务
  }
});

  // 4. 发一句话
  await agent.prompt("现在时间几点了");
