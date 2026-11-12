import { test } from "vitest";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
const composablesDir = join(repoRoot, "frontend/src/composables");

function pythonSource(modulePath) {
	const base = join(repoRoot, ...modulePath.split("."));
	for (const candidate of [`${base}.py`, join(base, "__init__.py")]) {
		if (existsSync(candidate)) return readFileSync(candidate, "utf8");
	}
	return null;
}

test("every full one_bpmn method path in a composable names a Python function that exists", () => {
	const missing = [];
	for (const file of readdirSync(composablesDir).filter((f) => f.endsWith(".js"))) {
		const text = readFileSync(join(composablesDir, file), "utf8");
		// A path followed by "." is a prefix joined to a name at run time.
		for (const [, path] of text.matchAll(/\/api\/method\/(one_bpmn(?:\.\w+)+)(?![.\w])/g)) {
			const parts = path.split(".");
			const fn = parts.pop();
			const source = pythonSource(parts.join("."));
			if (!source || !new RegExp(`^def ${fn}\\(`, "m").test(source)) {
				missing.push(`${file}: ${path}`);
			}
		}
	}
	assert.deepEqual(missing, []);
});
