/**
 * Web Stream Middleware — unified input/output processing for all web models.
 *
 * Input:  extract last user message → strip metadata → inject tool prompt
 * Output: parse tool calls from response → emit ToolCall events
 *
 * This middleware replaces the per-stream prompt manipulation that was
 * previously duplicated across 13 stream files.
 */

import type { StreamFn } from "@mariozechner/pi-agent-core";
import {
  createAssistantMessageEventStream,
  type AssistantMessage,
  type AssistantMessageEvent,
  type TextContent,
  type ToolCall,
} from "@mariozechner/pi-ai";
import { stripInboundMeta } from "../streams/strip-inbound-meta.js";
import { extractToolCall } from "./web-tool-parser.js";
import { shouldInjectToolPrompt, getToolPrompt, IDENTITY_PREFIX } from "./web-tool-prompt.js";

/**
 * Quick keyword check: does this message likely need tool use?
 * Only inject tool prompt when keywords suggest a tool action,
 * keeping normal chat messages short to reduce ban risk.
 */
function needsToolInjection(message: string): boolean {
  const lower = message.toLowerCase().trim();

  // Short messages (≤20 chars) are almost always follow-ups in a tool-use conversation.
  // Inject tools so the bot can continue multi-step tasks without losing tool access.
  if (lower.length <= 20) {
    return true;
  }

  const keywords = [
    // File operations
    "文件",
    "file",
    "<file ",   // OpenClaw attachment XML block injected on file uploads
    "csv",
    ".csv",
    "read",
    "write",
    "创建",
    "写入",
    "读取",
    "打开",
    "保存",
    "桌面",
    "desktop",
    "目录",
    "directory",
    "folder",
    "文件夹",
    // Command execution
    "执行",
    "运行",
    "命令",
    "command",
    "run",
    "exec",
    "terminal",
    "终端",
    "shell",
    // Web operations
    "搜索",
    "search",
    "查找",
    "查询",
    "fetch",
    "抓取",
    "网页",
    "url",
    "http",
    "天气",
    "weather",
    "新闻",
    "news",
    // Message / outreach
    "发送",
    "send",
    "消息",
    "message",
    "通知",
    "notify",
    "outreach",
    "campaign",
    "sequence",
    "financing",
    "template",
    "email",
    // General tool hints
    "帮我",
    "help me",
    "查看",
    "check",
    "look",
    "看看",
    "show",
    "下载",
    "download",
    "安装",
    "install",
    "更新",
    "update",
    // Lead generation / B2B operations
    "lead",
    "leads",
    "generate",
    "prospect",
    "outreach",
    "b2b",
    "contact",
    "company",
    "companies",
    "pipeline",
    "enrich",
    "verify",
    "email",
    // Conversational follow-ups and confirmations
    "yes",
    "ok",
    "okay",
    "sure",
    "continue",
    "proceed",
    "next",
    "go ahead",
    "do it",
    "what about",
    "and the",
    "now check",
    "now read",
    "now look",
    "please",
    "please check",
    "please read",
    "please do",
    "please look",
    "please show",
    "please list",
    "please access",
    "please generate",
    "please find",
    "please run",
    "how is",
    "how about",
    "what is",
    "tell me",
    // Analysis and investigation
    "analys",
    "analyze",
    "analyse",
    "analysis",
    "inspect",
    "review",
    "investigat",
    "diagnos",
    "list",
    "ls ",
    "cat ",
    "find",
    "get",
    "access",
    "open",
    "load",
    "scan",
    "describe",
    "what is",
    "what's in",
    "tell me about",
    // Audit/test/confirm
    "study",
    "audit",
    "test",
    "run",
    "properly",
    "really",
    "confirm",
    "check if",
    "make sure",
    "try",
    "attempt",
    // Skills
    "skill",
    "sg-",
    "leadgen",
    "enrich",
    "verify",
    "/root/",
    "path",
  ];
  return keywords.some((kw) => lower.includes(kw));
}

/**
 * Wrap a web stream function with tool calling middleware.
 * - Rewrites context: only sends last user message + optional tool prompt
 * - Parses response: extracts tool_call JSON → emits ToolCall events
 */
export function wrapWithToolCalling(streamFn: StreamFn, api: string): StreamFn {
  return (model, context, options) => {
    // --- Input rewriting ---
    const messages = context.messages || [];
    const lastMsg = messages[messages.length - 1];

    // --- Determine user message (handles both normal turns and tool result feedback) ---
    let userMessage = "";
    let isToolResult = false;

    if (lastMsg?.role === "toolResult") {
      // Tool just executed — format result as user message so model can continue
      isToolResult = true;
      const tr = lastMsg as unknown as {
        toolCallId?: string;
        toolName?: string;
        content?: Array<{ type: string; text?: string }>;
      };
      let resultText = "";
      if (Array.isArray(tr.content)) {
        for (const part of tr.content) {
          if (part.type === "text" && part.text) {
            resultText += part.text;
          }
        }
      }
      userMessage = `Tool ${tr.toolName || "unknown"} returned: ${resultText}\n\nContinue the task. Check if more steps remain. If yes, make the NEXT tool call immediately. Only answer the user when every required step is finished.`;
    } else {
      // Extract just the last user message (web models can't handle full context)
      const lastUserMsg = [...messages].toReversed().find((m) => m.role === "user");
      if (lastUserMsg) {
        if (typeof lastUserMsg.content === "string") {
          userMessage = lastUserMsg.content;
        } else if (Array.isArray(lastUserMsg.content)) {
          userMessage = (lastUserMsg.content as TextContent[])
            .filter((p) => p.type === "text")
            .map((p) => p.text)
            .join("");
        }
      }
      // Strip OpenClaw metadata
      userMessage = stripInboundMeta(userMessage);
    }

    if (!userMessage) {
      return streamFn(model, context, options);
    }

    // Inject tool prompt when the message likely needs tool use.
    // Tool results ALWAYS get tool injection so the model can continue multi-step tasks.
    const hasAgentTools = (context.tools?.length ?? 0) > 0;
    const injectTools =
      shouldInjectToolPrompt(api) && hasAgentTools && (isToolResult || needsToolInjection(userMessage));

    // Context preservation for short replies: web models see only the last user message,
    // so multi-turn workflows (e.g. bot asks question → user replies with a name) lose context.
    // Prepend the bot's previous message so the model understands what the short reply refers to.
    let contextPrefix = "";
    let contextPrefixStatus: "included" | "truncated" | "skipped" = "skipped";
    if (!isToolResult && injectTools && userMessage.length <= 120) {
      const assistantMsgs = messages.filter((m) => m.role === "assistant");
      const lastAssistant = assistantMsgs[assistantMsgs.length - 1];
      if (lastAssistant) {
        let assistantText = "";
        if (typeof lastAssistant.content === "string") {
          assistantText = lastAssistant.content;
        } else if (Array.isArray(lastAssistant.content)) {
          assistantText = (lastAssistant.content as TextContent[])
            .filter((p) => p.type === "text")
            .map((p) => p.text)
            .join("");
        }
        if (assistantText) {
          const MAX_PREFIX_LEN = 4000;
          const TAIL_LEN = 2000;
          const snippet = assistantText.length > MAX_PREFIX_LEN
            ? "…" + assistantText.slice(-TAIL_LEN)
            : assistantText;
          contextPrefix = `Your previous message to the user was:\n"${snippet.replace(/"/g, '\\"')}"\n\nThe user replied:\n`;
          contextPrefixStatus = assistantText.length > MAX_PREFIX_LEN ? "truncated" : "included";
        }
      }
    }

    // Build the prompt: identity prefix always + tool prompt (if applicable) + context prefix + user message
    const prompt = injectTools
      ? IDENTITY_PREFIX + getToolPrompt(api) + contextPrefix + userMessage
      : IDENTITY_PREFIX + userMessage;

    console.log(
      `[WebStreamMiddleware] api=${api} injectTools=${injectTools} isToolResult=${isToolResult} promptLen=${prompt.length} userMsgLen=${userMessage.length} contextPrefix=${contextPrefixStatus}`,
    );

    // Create modified context with just the user message.
    // Spread the original context to preserve the full type, then override.
    const modifiedContext = Object.assign({}, context, {
      messages: [{ role: "user" as const, content: prompt }],
      tools: [] as typeof context.tools,
      systemPrompt: "",
    });

    if (!injectTools) {
      // No tool calling — just pass through with cleaned context
      return streamFn(model, modifiedContext, options);
    }

    // --- With tool calling: wrap the output stream ---
    const originalStreamOrPromise = streamFn(model, modifiedContext, options);
    const wrappedStream = createAssistantMessageEventStream();

    // Process events from original stream
    const processEvents = async () => {
      try {
        const originalStream = await Promise.resolve(originalStreamOrPromise);
        let accumulatedText = "";
        const bufferedEvents: AssistantMessageEvent[] = [];

        for await (const event of originalStream) {
          if (event.type === "error") {
            wrappedStream.push(event);
            continue;
          }

          // On stream completion, check final message for tool calls
          if (event.type === "done") {
            // Use final message content (already deduplicated by stream parser)
            // instead of accumulating text_delta events which may contain duplicates
            const finalMsg = event.message;
            if (finalMsg && Array.isArray(finalMsg.content)) {
              for (const part of finalMsg.content) {
                if (part.type === "text" && part.text) {
                  accumulatedText = part.text;
                }
              }
            }

            const toolCall = extractToolCall(accumulatedText);

            if (toolCall) {
              const toolId = `web_tool_${Date.now()}`;

              // Emit tool call events
              const toolCallPart: ToolCall = {
                type: "toolCall",
                id: toolId,
                name: toolCall.tool,
                arguments: toolCall.parameters,
              };

              const toolMsg: AssistantMessage = {
                role: "assistant",
                content: [toolCallPart],
                stopReason: "toolUse",
                api: model.api,
                provider: model.provider,
                model: model.id,
                usage: finalMsg?.usage ?? {
                  input: 0,
                  output: 0,
                  cacheRead: 0,
                  cacheWrite: 0,
                  totalTokens: 0,
                  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
                },
                timestamp: Date.now(),
              };

              wrappedStream.push({
                type: "toolcall_start",
                contentIndex: 0,
                partial: toolMsg,
              });
              wrappedStream.push({
                type: "toolcall_end",
                contentIndex: 0,
                toolCall: toolCallPart,
                partial: toolMsg,
              });
              wrappedStream.push({
                type: "done",
                reason: "toolUse",
                message: toolMsg,
              });
            } else {
              for (const bufferedEvent of bufferedEvents) {
                wrappedStream.push(bufferedEvent);
              }
              // No tool call — forward the done event as-is
              wrappedStream.push(event);
            }
          } else {
            // Buffer stream text until completion so raw tool JSON is never sent
            // to downstream channels before we decide whether it is a tool call.
            bufferedEvents.push(event);
          }
        }
      } catch (err) {
        wrappedStream.push({
          type: "error",
          reason: "error",
          error: {
            role: "assistant",
            content: [],
            stopReason: "error",
            errorMessage: err instanceof Error ? err.message : String(err),
            api: model.api,
            provider: model.provider,
            model: model.id,
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
        } as AssistantMessageEvent);
      } finally {
        wrappedStream.end();
      }
    };

    queueMicrotask(() => void processEvents());
    return wrappedStream;
  };
}
