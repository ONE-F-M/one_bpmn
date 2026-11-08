import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ordinal } from "../../src/utils/a2aFormat";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("ordinal", () => {
	it("uses st, nd and rd for 1, 2 and 3", () => {
		expect(ordinal(1)).toBe("1st");
		expect(ordinal(2)).toBe("2nd");
		expect(ordinal(3)).toBe("3rd");
	});

	it("uses th from 4 on", () => {
		expect(ordinal(4)).toBe("4th");
		expect(ordinal(10)).toBe("10th");
	});

	it("uses th for the teens, and picks the suffix back up after them", () => {
		expect(ordinal(11)).toBe("11th");
		expect(ordinal(12)).toBe("12th");
		expect(ordinal(13)).toBe("13th");
		expect(ordinal(21)).toBe("21st");
		expect(ordinal(22)).toBe("22nd");
		expect(ordinal(111)).toBe("111th");
	});
});

describe("hand-back outcome wording", () => {
	it("builds the count with ordinal, not a hand-written st/th", () => {
		const source = read(
			"../../src/components/A2A/A2ADelegationActions/A2ADelegationActions.vue",
		);
		expect(source).toContain("ordinal(redelegateOutcome.by_a_person)");
		expect(source).not.toMatch(/>st<\/span>/);
	});
});

describe("tasks agent filter", () => {
	it("sends the chosen agent to list_tasks as agent_configuration", () => {
		const source = read("../../src/components/A2A/A2ATasks/A2ATasks.vue");
		expect(source).toMatch(/agent_configuration:\s*filters\.agent\s*\|\|\s*undefined/);
	});
});
