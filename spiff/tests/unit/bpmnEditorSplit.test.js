import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";

const src = new URL("../../src/", import.meta.url);
const EDITOR_DIR = "components/Editor/";
const PARTS = {
	BpmnEditor: true,
	BpmnEditorToolbar: true,
	BpmnMobileToolbar: false,
	BpmnProsAlly: true,
	BpmnPropertiesPanel: true,
	BpmnCommentSection: true,
	BpmnCommentPanel: true,
	BpmnInlineComment: true,
	BpmnContextMenu: true,
};
const read = (path) => readFileSync(new URL(path, src), "utf8");
const files = (part) => readdirSync(new URL(`${EDITOR_DIR}${part}/`, src)).sort();

describe("BpmnEditor split", () => {
	it("gives each part a folder with its component and, when it has rules, its stylesheet", () => {
		for (const [part, hasCss] of Object.entries(PARTS)) {
			expect(files(part), part).toEqual(
				hasCss ? [`${part}.css`, `${part}.vue`] : [`${part}.vue`],
			);
		}
	});

	it("loads the stylesheet that sits next to each part", () => {
		for (const [part, hasCss] of Object.entries(PARTS)) {
			const source = read(`${EDITOR_DIR}${part}/${part}.vue`);
			if (hasCss)
				expect(source, part).toMatch(
					new RegExp(`<style( scoped)? src="./${part}.css"></style>`),
				);
			else expect(source, part).not.toContain("<style");
		}
	});

	it("keeps no stylesheet of the old shared names", () => {
		const top = readdirSync(new URL(EDITOR_DIR, src));
		expect(top).not.toContain("bpmnEditorBase.css");
		expect(top).not.toContain("bpmnEditorPanel.css");
	});

	it("composes the parts from the shell", () => {
		const shell = read(`${EDITOR_DIR}BpmnEditor/BpmnEditor.vue`);
		for (const part of Object.keys(PARTS).filter((p) => p !== "BpmnEditor")) {
			if (part === "BpmnCommentSection") continue;
			expect(shell, part).toContain(`from "../${part}/${part}.vue"`);
		}
		expect(read(`${EDITOR_DIR}BpmnPropertiesPanel/BpmnPropertiesPanel.vue`)).toContain(
			'from "../BpmnCommentSection/BpmnCommentSection.vue"',
		);
	});
});
