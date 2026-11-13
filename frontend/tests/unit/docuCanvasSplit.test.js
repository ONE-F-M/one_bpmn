import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";

const src = new URL("../../src/", import.meta.url);
const read = (path) => readFileSync(new URL(path, src), "utf8");
const lineCount = (path) => read(path).split("\n").length - 1;

const DOCU_DIR = "components/Docu/";
const COMPOSABLES = [
	"useDocu",
	"useDocuAutosave",
	"useDocuChat",
	"useDocuHistory",
	"useDocuIr",
	"useDocuSettings",
	"useDocuTree",
].map((name) => `composables/Docu/${name}.js`);
const UTILS = ["docuApi", "docuFieldDefs", "docuSettingsDefs"].map((name) => `utils/${name}.js`);
const PART_DIRS = readdirSync(new URL(DOCU_DIR, src));
const docuFiles = PART_DIRS.flatMap((dir) =>
	readdirSync(new URL(`${DOCU_DIR}${dir}/`, src)).map((f) => `${DOCU_DIR}${dir}/${f}`),
);
const partFile = (part) => `${DOCU_DIR}${part}/${part}.vue`;
const SHELL = partFile("DocuCanvas");

describe("DocuCanvas split", () => {
	it("gives the four parts the story names, and the rest, a folder each with its component and stylesheet", () => {
		for (const part of [
			"DocuCanvas",
			"DocuFormCanvas",
			"DocuFieldCard",
			"DocuChangesPreview",
			"DocuApplyBar",
			"DocuSettingsView",
			"DocuPermissionRules",
			"DocuPropertiesPanel",
		]) {
			expect(PART_DIRS, part).toContain(part);
			const files = readdirSync(new URL(`${DOCU_DIR}${part}/`, src)).sort();
			expect(files, part).toEqual([`${part}.css`, `${part}.vue`]);
		}
		expect(PART_DIRS).toHaveLength(8);
	});

	it("keeps every file under 500 lines and the shell under 300", () => {
		for (const file of [...docuFiles, ...COMPOSABLES, ...UTILS]) {
			expect(lineCount(file), file).toBeLessThan(500);
		}
		expect(lineCount(SHELL)).toBeLessThan(300);
	});

	it("composes the parts from the shell", () => {
		const shell = read(SHELL);
		for (const part of [
			"DocuFormCanvas",
			"DocuSettingsView",
			"DocuPropertiesPanel",
			"DocuChangesPreview",
			"DocuApplyBar",
		]) {
			expect(shell, part).toMatch(new RegExp(`import ${part} from`));
			expect(shell, part).toMatch(new RegExp(`<${part}[\\s/>]`));
		}
		expect(read(partFile("DocuFormCanvas"))).toMatch(/<DocuFieldCard/);
		expect(read(partFile("DocuSettingsView"))).toMatch(/<DocuPermissionRules/);
	});

	it("loads the stylesheet that sits next to each part", () => {
		for (const file of docuFiles.filter((f) => f.endsWith(".vue"))) {
			const name = file
				.split("/")
				.pop()
				.replace(/\.vue$/, "");
			expect(read(file), file).toContain(`<style scoped src="./${name}.css"></style>`);
		}
	});

	it("leaves no work-item id in the moved code", () => {
		for (const file of [...docuFiles, ...COMPOSABLES, ...UTILS]) {
			expect(read(file), file).not.toMatch(/WI-\d+/);
		}
	});
});

describe("endpoints the Docu canvas calls", () => {
	const apiModule = read("utils/docuApi.js").match(/processa\.api\.(\w+)\./)[1];
	const python = readFileSync(
		new URL(`../../../processa/api/${apiModule}.py`, import.meta.url),
		"utf8",
	);
	const sources = [...docuFiles.filter((f) => /\.(vue)$/.test(f)), ...COMPOSABLES]
		.map(read)
		.join("\n");
	const called = [...new Set([...sources.matchAll(/\$\{DOCU_API\}(\w+)/g)].map((m) => m[1]))];

	it("calls the seven endpoints the original screen called", () => {
		expect(called.sort()).toEqual([
			"apply_client_script",
			"apply_doctype",
			"can_change_forms",
			"get_doctype_schema",
			"list_modules",
			"list_roles",
			"preview_doctype",
		]);
	});

	it("exist in the backend module as whitelisted methods", () => {
		for (const name of called) {
			expect(python, `${apiModule}.${name}`).toMatch(
				new RegExp(`@frappe\\.whitelist\\([^)]*\\)\\s*\\ndef ${name}\\(`),
			);
		}
	});
});
