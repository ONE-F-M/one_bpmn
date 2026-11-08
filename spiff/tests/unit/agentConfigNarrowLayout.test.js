import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = [
	"../../src/components/Modals/AIAgentConfigModal/AIAgentConfigModal.css",
	"../../src/components/AgentConfig/AgentConfigAssistant/AgentConfigAssistant.css",
]
	.map((path) => readFileSync(new URL(path, import.meta.url), "utf8"))
	.join("\n");
const narrow = css.slice(css.indexOf("@media (max-width: 640px)"));

describe("agent config dialog at narrow widths", () => {
	it("stacks the chat pane below the form", () => {
		expect(narrow).toMatch(/\.ai-agent-modal\s*{[^}]*flex-direction:\s*column/);
		expect(narrow).toMatch(/\.assistant-panel\s*{[^}]*order:\s*0/);
	});

	it("gives the form the full dialog width", () => {
		expect(narrow).toMatch(/\.ai-agent-modal\s*{[^}]*width:\s*95vw/);
	});
});
