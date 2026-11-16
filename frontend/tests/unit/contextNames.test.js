import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const src = fileURLToPath(new URL("../../src/", import.meta.url));
const read = (path) => readFileSync(join(src, path), "utf8");
const list = (dir) => readdirSync(join(src, dir));
const listComposables = () =>
	readdirSync(join(src, "composables"), { recursive: true }).filter((f) => f.endsWith(".js"));

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
	assert.ok(files.length > 0, "no composable files found");
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
	const composables = listComposables()
		.filter((f) => /(?:^|\/)(useProcess|useProductionReview)/.test(f))
		.map((f) => `composables/${f}`);
	const provided = providedNames(
		composables,
		"pc",
		"composables/Process/useProcessState.js",
		"const pc = {",
	);
	for (const name of ["notifDialog", "props", "router", "route", "isMobile"]) provided.add(name);
	const components = list("components/Editor")
		.filter((f) => /^Process/.test(f))
		.map((f) => (f.endsWith(".vue") ? f : `${f}/${f}.vue`));
	for (const file of components) {
		const missing = destructured(read(`components/Editor/${file}`), "pc").filter(
			(n) => !provided.has(n),
		);
		assert.deepEqual(missing, [], `${file} reads names the context does not provide`);
	}
});

test("every name an editor component reads from the editor context is provided by it", () => {
	const composables = listComposables()
		.filter((f) => /(?:^|\/)useEditor/.test(f))
		.map((f) => `composables/${f}`);
	const provided = providedNames(
		composables,
		"ed",
		"composables/Editor/useEditorState.js",
		"return {",
	);
	const components = list("components/Editor")
		.filter((f) => /^Bpmn/.test(f))
		.map((f) => (f.endsWith(".vue") ? f : `${f}/${f}.vue`));
	for (const file of components) {
		const missing = destructured(read(`components/Editor/${file}`), "ed").filter(
			(n) => !provided.has(n),
		);
		assert.deepEqual(missing, [], `${file} reads names the context does not provide`);
	}
});

test("every name an agent config component reads from the dialog context is provided by it", () => {
	const composables = listComposables()
		.filter((f) => /(?:^|\/)useAgentConfig(?!LintState)/.test(f))
		.map((f) => `composables/${f}`);
	const provided = providedNames(
		composables,
		"ac",
		"composables/AgentConfig/useAgentConfigState.js",
		"return {",
	);
	const parts = list("components/AgentConfig").filter((d) => /^AgentConfig/.test(d));
	assert.equal(parts.length, 8);
	for (const part of parts) {
		const files = list(`components/AgentConfig/${part}`).sort();
		assert.ok(
			[[`${part}.vue`], [`${part}.css`, `${part}.vue`]].some(
				(layout) => JSON.stringify(layout) === JSON.stringify(files),
			),
			`${part} holds ${files}`,
		);
	}
	for (const part of parts) {
		const file = `${part}/${part}.vue`;
		const missing = destructured(read(`components/AgentConfig/${file}`), "ac").filter(
			(n) => !provided.has(n),
		);
		assert.deepEqual(missing, [], `${file} reads names the context does not provide`);
	}
	const shell = destructured(
		read("components/Modals/AIAgentConfigModal/AIAgentConfigModal.vue"),
		"ac",
	);
	assert.deepEqual(
		shell.filter((n) => !provided.has(n)),
		[],
	);
});
