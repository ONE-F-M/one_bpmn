import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const dir = fileURLToPath(new URL("../../src/composables/", import.meta.url));
const read = (name) => readFileSync(join(dir, name), "utf8");

test("the command stack listeners subscribe to the real bpmn-js event names", () => {
	const canvas = read("Editor/useEditorCanvas.js");
	const elements = read("Editor/useEditorElements.js");
	assert.match(canvas, /eventBus\.on\("commandStack\.changed"/);
	assert.match(canvas, /modeler\.get\("commandStack"\)/);
	assert.match(elements, /eventBus\.on\("commandStack\.shape\.replace\.postExecute"/);
	assert.match(elements, /eventBus\.on\("commandStack\.elements\.delete\.postExecute"/);
});

test("no editor composable rewrites a shared name inside a string literal", () => {
	for (const file of readdirSync(dir).filter((f) => f.startsWith("useEditor"))) {
		assert.doesNotMatch(read(file), /["'`]ed\./, file);
	}
});
