import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (url) => readFileSync(url, "utf8");
const apiSource = read(new URL("../../src/utils/a2aApi.js", import.meta.url));
const partsDir = new URL("../../src/components/A2A/", import.meta.url);
const modalsDir = new URL("../../src/components/Modals/", import.meta.url);
const a2aModals = ["A2AClarificationModal", "A2ADelegationModal"];
const sources = [
	read(new URL("../../src/pages/A2A.vue", import.meta.url)),
	read(new URL("../../src/composables/useA2AList.js", import.meta.url)),
	...readdirSync(partsDir)
		.flatMap((dir) => readdirSync(new URL(`${dir}/`, partsDir)))
		.filter((f) => f.endsWith(".vue"))
		.map((f) => read(new URL(`${f.replace(/\.vue$/, "")}/${f}`, partsDir))),
	...a2aModals.map((m) => read(new URL(`${m}/${m}.vue`, modalsDir))),
].join("\n");

const prefixModule = (constant) =>
	apiSource.match(new RegExp(`${constant}\\s*=\\s*"/api/method/processa\\.api\\.(\\w+)\\."`))[1];

const calledBy = (constant) =>
	[...sources.matchAll(new RegExp(`${constant}\\s*\\+\\s*"(\\w+)"`, "g"))].map((m) => m[1]);

describe("endpoints the A2A page calls", () => {
	for (const constant of ["A2A_API", "CLARIFY_API"]) {
		it(`exist in the backend module behind ${constant}`, () => {
			const module = prefixModule(constant);
			const python = read(new URL(`../../../processa/api/${module}.py`, import.meta.url));
			const names = [...new Set(calledBy(constant))];
			expect(names.length).toBeGreaterThan(0);
			for (const name of names) {
				expect(python, `${module}.${name}`).toMatch(new RegExp(`def ${name}\\(`));
			}
		});
	}
});
