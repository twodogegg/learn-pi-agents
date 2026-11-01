// 03-A：多轮对话与记忆
// 问题：同一个 agent 连续 prompt()，它能记住上一句话吗？"记忆"到底存在哪？
import { makeAgent, makeGetTimeTool, attachPrinter, ask, section, printMessages } from "./common.js";

const systemPrompt = "You are a helpful assistant. 需要时间信息时必须调用 get_time 工具，不要猜。用中文简短回答。";

// ---------- A. 同一个 agent，连续提问 ----------
section("A. 同一个 agent 连续提问");
const agent = makeAgent({ systemPrompt, tools: [makeGetTimeTool()] });
attachPrinter(agent);

await ask(agent, "东京现在几点？");
printMessages(agent.state.messages, "第 1 问之后");

await ask(agent, "那纽约呢？"); // 这句话单独看毫无意义，必须靠上文才能懂
printMessages(agent.state.messages, "第 2 问之后");

// ---------- B. 全新 agent，没有历史 ----------
section("B. 全新 agent，没有历史，直接问同样的话");
const fresh = makeAgent({ systemPrompt, tools: [makeGetTimeTool()] });
attachPrinter(fresh);
await ask(fresh, "那纽约呢？");

// ---------- C. reset ----------
// 文档只列出了 agent.reset()，没说明具体行为，这里用实验验证
section("C. reset() 之后");
console.log(`reset 前 messages 条数：${agent.state.messages.length}`);
agent.reset();
console.log(`reset 后 messages 条数：${agent.state.messages.length}`);
await ask(agent, "我刚才问过你什么？");
printMessages(agent.state.messages, "reset 后再问一句");
