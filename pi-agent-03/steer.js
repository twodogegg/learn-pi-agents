// 03-B：steer() 与 followUp()
// steer：工具还在运行时插话，当前 assistant 消息的工具全部完成后注入，模型在下一个 turn 响应
// followUp：只在"本来要结束了"（没有工具调用、也没有 steer 消息）时才检查，有就再开一个 turn
import { makeAgent, makeGetTimeTool, attachPrinter, printMessages } from "./common.js";

const agent = makeAgent({
  systemPrompt: "You are a helpful assistant. 需要时间信息时必须调用 get_time 工具，不要猜。用中文回答。",
  // 每次调用故意拖 2 秒，给"工具运行中"留出时间窗口
  tools: [makeGetTimeTool({ delayMs: 2000 })],
});
attachPrinter(agent);

let injected = false;
agent.subscribe((event) => {
  // 第一个工具开始执行时，同时排队 steer 和 followUp（都是消息对象，不是字符串）
  if (event.type === "tool_execution_start" && !injected) {
    injected = true;
    console.log("\n\x1b[31m[steer + followUp 已排队]\x1b[0m");

    agent.steer({
      role: "user",
      content: "改主意了：只保留东京的结果，纽约和伦敦忽略。回答控制在一句话。",
      timestamp: Date.now(),
    });
    agent.followUp({
      role: "user",
      content: "最后再用英文把结论重复一遍。",
      timestamp: Date.now(),
    });
  }
});

await agent.prompt("查一下东京、纽约、伦敦现在几点。");

printMessages(agent.state.messages, "最终 messages：留意两条插入的 user 消息出现在哪个位置");
