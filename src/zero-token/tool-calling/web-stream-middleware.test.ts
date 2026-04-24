import { describe, expect, it } from "vitest";
import { wrapWithToolCalling } from "./web-stream-middleware.js";

describe("web-stream-middleware", () => {
  it("suppresses streamed tool json and emits a tool call on done", async () => {
    const streamFn = () =>
      (async function* () {
        yield {
          type: "text_start",
          contentIndex: 0,
          partial: { role: "assistant", content: [], stopReason: "stop", timestamp: Date.now() },
        };
        yield {
          type: "text_delta",
          contentIndex: 0,
          delta: '{"tool":"read","parameters":{"path":"/root/.openclaw-zero/workspace/AGENTS.md"}}',
          partial: { role: "assistant", content: [], stopReason: "stop", timestamp: Date.now() },
        };
        yield {
          type: "done",
          reason: "stop",
          message: {
            role: "assistant",
            content: [
              {
                type: "text",
                text: '{"tool":"read","parameters":{"path":"/root/.openclaw-zero/workspace/AGENTS.md"}}',
              },
            ],
            stopReason: "stop",
            api: "deepseek-web",
            provider: "deepseek-web",
            model: "deepseek-chat",
            usage: {
              input: 0,
              output: 0,
              cacheRead: 0,
              cacheWrite: 0,
              totalTokens: 0,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
            },
            timestamp: Date.now(),
          },
        };
      })();

    const wrapped = wrapWithToolCalling(streamFn as any, "deepseek-web");
    const stream = wrapped(
      { api: "deepseek-web", provider: "deepseek-web", id: "deepseek-chat" } as any,
      {
        messages: [{ role: "user", content: "read /root/.openclaw-zero/workspace/AGENTS.md" }],
        tools: [{ name: "read" }],
      } as any,
      undefined,
    );

    const events: any[] = [];
    for await (const event of stream as AsyncIterable<any>) {
      events.push(event);
    }

    expect(events.some((event) => event.type === "text_delta")).toBe(false);
    expect(events.some((event) => event.type === "toolcall_end")).toBe(true);
    const done = events.find((event) => event.type === "done");
    expect(done?.reason).toBe("toolUse");
  });

  it("replays buffered text events when the reply is not a tool call", async () => {
    const streamFn = () =>
      (async function* () {
        yield {
          type: "text_start",
          contentIndex: 0,
          partial: { role: "assistant", content: [], stopReason: "stop", timestamp: Date.now() },
        };
        yield {
          type: "text_delta",
          contentIndex: 0,
          delta: "Hello there",
          partial: { role: "assistant", content: [], stopReason: "stop", timestamp: Date.now() },
        };
        yield {
          type: "done",
          reason: "stop",
          message: {
            role: "assistant",
            content: [{ type: "text", text: "Hello there" }],
            stopReason: "stop",
            api: "deepseek-web",
            provider: "deepseek-web",
            model: "deepseek-chat",
            usage: {
              input: 0,
              output: 0,
              cacheRead: 0,
              cacheWrite: 0,
              totalTokens: 0,
              cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
            },
            timestamp: Date.now(),
          },
        };
      })();

    const wrapped = wrapWithToolCalling(streamFn as any, "deepseek-web");
    const stream = wrapped(
      { api: "deepseek-web", provider: "deepseek-web", id: "deepseek-chat" } as any,
      {
        messages: [{ role: "user", content: "read the file and explain it" }],
        tools: [{ name: "read" }],
      } as any,
      undefined,
    );

    const events: any[] = [];
    for await (const event of stream as AsyncIterable<any>) {
      events.push(event);
    }

    expect(events.some((event) => event.type === "text_delta")).toBe(true);
    expect(events.some((event) => event.type === "toolcall_end")).toBe(false);
    const done = events.find((event) => event.type === "done");
    expect(done?.reason).toBe("stop");
  });
});
