import { describe, expect, it } from "vitest";
import { getToolPrompt, IDENTITY_PREFIX } from "./web-tool-prompt.js";

describe("web-tool-prompt", () => {
  it("uses native-tool guidance for qwen web", () => {
    const prompt = getToolPrompt("qwen-web");
    expect(prompt).toContain("Use Qwen native tools instead");
    expect(prompt).toContain("Do NOT call OpenClaw-injected tools");
    expect(prompt).toContain("code_interpreter");
    expect(prompt).not.toContain("reply ONLY with the tool_json block");
  });

  it("keeps injected-tool prompt for deepseek web", () => {
    const prompt = getToolPrompt("deepseek-web");
    expect(prompt).toContain("reply ONLY with the tool_json block");
    expect(prompt).toContain('{"tool":"plus_one"');
  });

  it("includes anti-hallucination identity rules", () => {
    expect(IDENTITY_PREFIX).toContain("Do not fabricate contacts, titles, or source support");
    expect(IDENTITY_PREFIX).toContain("Do not add \"CEO\", email, phone, or LinkedIn unless the source supports it");
  });
});
