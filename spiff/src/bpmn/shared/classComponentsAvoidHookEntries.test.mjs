// node --test spiff/src/bpmn/shared/classComponentsAvoidHookEntries.test.mjs
// A class component rendering a panel entry crashes on its own re-render and stalls the panel's dropdowns.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const BPMN_DIR = join(fileURLToPath(new URL(".", import.meta.url)), "..");

function jsFiles(dir) {
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		if (statSync(path).isDirectory()) return jsFiles(path);
		return name.endsWith(".js") ? [path] : [];
	});
}

function classBodies(source) {
	const bodies = [];
	for (const match of source.matchAll(/class (\w+) extends Component \{/g)) {
		let depth = 1;
		let i = match.index + match[0].length;
		while (depth && i < source.length) {
			if (source[i] === "{") depth += 1;
			else if (source[i] === "}") depth -= 1;
			i += 1;
		}
		bodies.push([match[1], source.slice(match.index, i)]);
	}
	return bodies;
}

test("no class component renders a hook-based properties-panel entry", () => {
	const offenders = [];
	for (const file of jsFiles(BPMN_DIR)) {
		for (const [name, body] of classBodies(readFileSync(file, "utf8"))) {
			const entries = body.match(/h\(\w+Entry\b/g);
			if (entries) offenders.push(`${file.slice(BPMN_DIR.length + 1)}: ${name} renders ${entries.join(", ")}`);
		}
	}
	assert.deepEqual(offenders, []);
});
