import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";

const src = new URL("../../src/", import.meta.url);
const EDITOR_DIR = "components/Editor/";
const WITH_CSS = ["ProcessDmnTab", "ProcessLauncherDialogs", "ProcessLogixTab"];
const WITHOUT_CSS = [
	"ProcessToolbar",
	"ProcessActions",
	"ProcessDiagramTab",
	"ProcessScriptDialog",
	"ProcessDeployTab",
	"ProcessConfigurationTab",
	"BpmnDocuPanel",
];
const folderFiles = (part) => readdirSync(new URL(`${EDITOR_DIR}${part}/`, src)).sort();

describe("Editor part folders", () => {
	it("gives each process part a folder holding its component and stylesheet", () => {
		const dirs = readdirSync(new URL(EDITOR_DIR, src));
		for (const part of WITH_CSS) {
			expect(dirs, part).toContain(part);
			expect(folderFiles(part), part).toEqual([`${part}.css`, `${part}.vue`]);
		}
		for (const part of WITHOUT_CSS) {
			expect(dirs, part).toContain(part);
			expect(folderFiles(part), part).toEqual([`${part}.vue`]);
		}
	});

	it("loads the stylesheet that sits next to the part and no other", () => {
		for (const part of [...WITH_CSS, ...WITHOUT_CSS]) {
			const vue = readFileSync(new URL(`${EDITOR_DIR}${part}/${part}.vue`, src), "utf8");
			const styles = vue.match(/<style[^>]*>/g) || [];
			expect(styles, part).toEqual(
				WITH_CSS.includes(part) ? [`<style scoped src="./${part}.css">`] : [],
			);
		}
	});

	it("keeps no shared page stylesheet or loose part file beside the folders", () => {
		const loose = readdirSync(new URL(EDITOR_DIR, src)).filter(
			(f) => /^(Process|processPage|BpmnDocuPanel)/.test(f) && /\.(vue|css)$/.test(f),
		);
		expect(loose).toEqual([]);
	});
});
