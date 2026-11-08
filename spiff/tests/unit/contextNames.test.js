import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const src = fileURLToPath(new URL("../../src/", import.meta.url));
const read = (path) => readFileSync(join(src, path), "utf8");
const list = (dir) => readdirSync(join(src, dir));

// Editor components, flat files and the <Part>/<Part>.vue of each part folder.
const editorComponents = () =>
	list("components/Editor").flatMap((entry) =>
		entry.endsWith(".vue") ? [entry] : [`${entry}/${entry}.vue`],
	);

// Names a composable puts on the shared context: Object.assign lists plus the state return object.
function providedNames(files, variable, stateFile, stateMarker) {
	const names = new Set();
	for (const file of files) {
		for (const match of read(file).matchAll(
			new RegExp(`Object\\.assign\\(${variable}, \\{([^}]*)\\}`, "g"),
		)) {
			match[1]
				.split(",")
				.map((n) => n.trim())
				.filter(Boolean)
				.forEach((n) => names.add(n));
		}
	}
	const state = read(stateFile);
	const block = state.slice(state.lastIndexOf(stateMarker));
	for (const match of block.matchAll(/^\t\t(\w+)[,:]/gm)) names.add(match[1]);
	return names;
}

function destructured(source, variable) {
	const match = source.match(new RegExp(`const \\{([^}]*)\\} = ${variable};`));
	return match
		? match[1]
				.split(",")
				.map((n) => n.trim())
				.filter(Boolean)
		: [];
}

test("every name a process component reads from the page context is provided by it", () => {
	const composables = list("composables")
		.filter((f) => /^(useProcess|useProductionReview)/.test(f))
		.map((f) => `composables/${f}`);
	const provided = providedNames(
		composables,
		"pc",
		"composables/useProcessState.js",
		"const pc = {",
	);
	for (const name of ["notifDialog", "props", "router", "route", "isMobile"]) provided.add(name);
	const components = editorComponents().filter((f) => /^Process.*\.vue$/.test(f));
	for (const file of components) {
		const missing = destructured(read(`components/Editor/${file}`), "pc").filter(
			(n) => !provided.has(n),
		);
		assert.deepEqual(missing, [], `${file} reads names the context does not provide`);
	}
});

test("every name an editor component reads from the editor context is provided by it", () => {
	const composables = list("composables")
		.filter((f) => /^useEditor/.test(f))
		.map((f) => `composables/${f}`);
	const provided = providedNames(composables, "ed", "composables/useEditorState.js", "return {");
	const components = editorComponents().filter((f) => /^Bpmn.*\.vue$/.test(f));
	for (const file of components) {
		const missing = destructured(read(`components/Editor/${file}`), "ed").filter(
			(n) => !provided.has(n),
		);
		assert.deepEqual(missing, [], `${file} reads names the context does not provide`);
	}
});

test("every name an agent config component reads from the dialog context is provided by it", () => {
	const composables = list("composables")
		.filter((f) => /^useAgentConfig(?!LintState)/.test(f))
		.map((f) => `composables/${f}`);
	const provided = providedNames(
		composables,
		"ac",
		"composables/useAgentConfigState.js",
		"return {",
	);
	const components = list("components/AgentConfig").filter((f) =>
		/^AgentConfig.*\.vue$/.test(f),
	);
	assert.equal(components.length, 7);
	for (const file of components) {
		const missing = destructured(read(`components/AgentConfig/${file}`), "ac").filter(
			(n) => !provided.has(n),
		);
		assert.deepEqual(missing, [], `${file} reads names the context does not provide`);
	}
	const shell = destructured(read("components/Modals/AIAgentConfigModal.vue"), "ac");
	assert.deepEqual(
		shell.filter((n) => !provided.has(n)),
		[],
	);
});
