import {
  makeAgent,
  makeGetTimeTool,
  attachPrinter,
  section,
  ask,
  printMessages
} from "../pi-agent-03/common.js";

// 创建一个 agent

const agent = makeAgent({
    systemPrompt: "你是一个时间助手。查询时间必须调用 get_time 工具，不要猜测。",
    tools: [makeGetTimeTool()]
})
agent.finishTurn = ({ message, toolResults }) => {
  console.log("\n[finishTurn 触发]");
  console.log("stopReason:", message.stopReason);
  console.log("工具结果数量:", toolResults.length);

  // 错误或中止不做额外决策
  if (
    message.stopReason === "error" ||
    message.stopReason === "aborted"
  ) {
    return;
  }

  // 本轮执行过工具，就结束整个 Agent Run
  if (toolResults.length > 0) {
    console.log("[决策] end");
    return { action: "end" };
  }

  console.log("[决策] 默认调度");
  return undefined;
};

// 3. 观察结束事件
agent.subscribe((event) => {
  if (event.type === "turn_end") {
    console.log("[turn_end]");
  }

  if (event.type === "agent_end") {
    console.log("[agent_end]");
  }
});

await ask(agent, "现在几点")


section("开始提问");

printMessages(agent.state.messages, "开始回答");

attachPrinter(agent)
