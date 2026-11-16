import { readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const components = new URL("../../src/components/", import.meta.url).pathname;
const MODALS = "Modals";
const MOVED = [
	"A2AClarificationModal",
	"A2ADelegationModal",
	"BpmnCommentModal",
	"BpmnMessageModal",
	"ProcessLauncherModal",
	"ProcessScriptModal",
	"EvalCompareModal",
	"EvalFromRunModal",
	"EvalThresholdsModal",
	"EvalDatasetModal",
	"EvalReassignModal",
	"EvalCaseEditorModal",
];

const vueFiles = readdirSync(components, { recursive: true }).filter((f) => f.endsWith(".vue"));

describe("dialog components", () => {
	it("keeps every dialog in components/Modals, in a folder of its own name", () => {
		const entries = readdirSync(join(components, MODALS), { withFileTypes: true });
		expect(entries.length).toBeGreaterThan(MOVED.length);
		for (const entry of entries) {
			expect(entry.isDirectory(), `${entry.name} is loose in Modals`).toBe(true);
			expect(entry.name, entry.name).toMatch(/Modal$/);
			const files = readdirSync(join(components, MODALS, entry.name));
			expect(files, entry.name).toContain(`${entry.name}.vue`);
			expect(
				files.filter((f) => !f.endsWith(".vue") && !f.endsWith(".css")),
				entry.name,
			).toEqual([]);
		}
	});

	it("has the twelve dialogs that used to sit in A2A, Editor and Evals", () => {
		const modals = readdirSync(join(components, MODALS));
		for (const name of MOVED) expect(modals, name).toContain(name);
	});

	it("leaves no component named Modal or Dialog outside components/Modals", () => {
		const outside = vueFiles.filter(
			(f) => !f.startsWith(`${MODALS}/`) && /(Modal|Dialog)s?\.vue$/.test(f),
		);
		expect(outside).toEqual([]);
	});
});
