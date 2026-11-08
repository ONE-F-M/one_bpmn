import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const partsDir = new URL("../../src/components/A2A/", import.meta.url);
const shell = new URL("../../src/pages/A2A.vue", import.meta.url);

const lineCount = (url) => readFileSync(url, "utf8").split("\n").length;
const parts = readdirSync(partsDir).filter((f) => f.endsWith(".vue"));

describe("A2A page split", () => {
	it("keeps the page a shell under 300 lines", () => {
		expect(lineCount(shell)).toBeLessThan(300);
	});

	it("keeps every part under 500 lines", () => {
		for (const part of parts) {
			expect(lineCount(new URL(part, partsDir)), part).toBeLessThan(500);
		}
	});

	it("has a part for remote agents, clients, tasks and delegations", () => {
		for (const part of ["A2ARemoteAgents", "A2AClients", "A2ATasks", "A2ADelegations"]) {
			expect(parts).toContain(`${part}.vue`);
		}
	});

	it("composes every tab part from the shell", () => {
		const source = readFileSync(shell, "utf8");
		for (const part of parts.filter(
			(p) => !/Modal|Actions|Pager|PageSize|AgentPicker/.test(p),
		)) {
			expect(source, part).toContain(part);
		}
	});
});
