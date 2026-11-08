import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const partsDir = new URL("../../src/components/A2A/", import.meta.url);
const read = (url) => readFileSync(url, "utf8");
const shell = read(new URL("../../src/pages/A2A.vue", import.meta.url));
const parts = Object.fromEntries(
	readdirSync(partsDir)
		.filter((f) => f.endsWith(".vue"))
		.map((f) => [f, read(new URL(f, partsDir))]),
);
const listParts = [
	"A2AOurAgents.vue",
	"A2ARemoteAgents.vue",
	"A2AClients.vue",
	"A2ATasks.vue",
	"A2ADelegations.vue",
	"A2AClarifications.vue",
];

describe("A2A page at narrow widths", () => {
	it("lets the header wrap and the tab bar scroll inside itself", () => {
		expect(shell).toMatch(/flex flex-wrap items-center justify-between/);
		expect(shell).toMatch(/<nav class="[^"]*max-w-full overflow-x-auto/);
		expect(shell).toMatch(/whitespace-nowrap/);
	});

	it("puts every table in its own horizontal scroll container", () => {
		for (const name of listParts) {
			expect(parts[name], name).toMatch(
				/<div v-else class="overflow-x-auto rounded-lg">\s*<table/,
			);
			expect(parts[name], name).toMatch(/<table class="w-full min-w-\[\d+rem\]/);
		}
	});

	it("never leaves a table straight in the panel", () => {
		for (const name of listParts) {
			expect(parts[name], name).not.toContain('<table v-else class="w-full text-sm');
		}
	});

	it("wraps the filter bars and stacks their inputs below the sm breakpoint", () => {
		for (const name of ["A2ATasks.vue", "A2ADelegations.vue", "A2AClarifications.vue"]) {
			expect(parts[name], name).toMatch(/border-b flex flex-wrap/);
			expect(parts[name], name).not.toMatch(/class="w-\d+"/);
			expect(parts[name], name).toMatch(/class="w-full sm:w-\d+"/);
		}
	});

	it("stacks a description and its action button on narrow screens", () => {
		for (const name of ["A2ARemoteAgents.vue", "A2AClients.vue"]) {
			expect(parts[name], name).toContain("flex flex-col gap-2 sm:flex-row");
		}
	});

	it("wraps the pagination footer", () => {
		expect(parts["A2APager.vue"]).toMatch(/flex flex-wrap/);
	});

	it("narrows the page gutter only below the sm breakpoint", () => {
		expect(shell).toContain("px-4 sm:px-6");
		for (const name of listParts) {
			expect(parts[name], name).not.toMatch(/(?<!sm:)px-6 py-[34]/);
		}
	});
});
