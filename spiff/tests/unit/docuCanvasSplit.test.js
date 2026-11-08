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
].map((name) => `composables/${name}.js`);
const UTILS = ["docuApi", "docuFieldDefs", "docuSettingsDefs"].map((name) => `utils/${name}.js`);
const docuFiles = readdirSync(new URL(DOCU_DIR, src)).map((f) => `${DOCU_DIR}${f}`);
const SHELL = `${DOCU_DIR}DocuCanvas.vue`;

describe("DocuCanvas split", () => {
	it("holds the four parts the story names, plus the settings and properties parts", () => {
		const names = docuFiles.map((f) => f.slice(DOCU_DIR.length));
		for (const part of [
			"DocuFormCanvas.vue",
			"DocuFieldCard.vue",
			"DocuChangesPreview.vue",
			"DocuApplyBar.vue",
			"DocuSettingsView.vue",
			"DocuPermissionRules.vue",
			"DocuPropertiesPanel.vue",
		]) {
			expect(names, part).toContain(part);
		}
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
		expect(read(`${DOCU_DIR}DocuFormCanvas.vue`)).toMatch(/<DocuFieldCard/);
		expect(read(`${DOCU_DIR}DocuSettingsView.vue`)).toMatch(/<DocuPermissionRules/);
	});

	it("gives each part its own scoped stylesheet", () => {
		for (const file of docuFiles.filter((f) => f.endsWith(".vue"))) {
			const css = read(file).match(/<style scoped src="@\/components\/Docu\/(\w+\.css)"/);
			expect(css, file).not.toBeNull();
			expect(docuFiles, file).toContain(`${DOCU_DIR}${css[1]}`);
		}
	});

	it("leaves no work-item id in the moved code", () => {
		for (const file of [...docuFiles, ...COMPOSABLES, ...UTILS]) {
			expect(read(file), file).not.toMatch(/WI-\d+/);
		}
	});
});

describe("endpoints the Docu canvas calls", () => {
	const apiModule = read("utils/docuApi.js").match(/one_bpmn\.api\.(\w+)\./)[1];
	const python = readFileSync(
		new URL(`../../../one_bpmn/api/${apiModule}.py`, import.meta.url),
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
