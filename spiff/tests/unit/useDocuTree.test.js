import { describe, expect, it } from "vitest";
import { useDocuTree } from "../../src/composables/useDocuTree.js";

const FIELDS = [
	{ fieldtype: "Tab Break", label: "Main" },
	{ fieldtype: "Section Break", label: "Basics" },
	{ fieldtype: "Data", label: "Title", fieldname: "title", reqd: 1, fetch_from: "owner.name" },
	{ fieldtype: "Column Break" },
	{ fieldtype: "Int", label: "Count", fieldname: "count" },
	{ fieldtype: "Section Break", label: "More" },
	{ fieldtype: "Date", label: "When", fieldname: "when" },
];

function built(raw = FIELDS) {
	const tree = useDocuTree();
	tree.buildTree(raw);
	return tree;
}

function click(tree, section, label) {
	tree.sectionMenu(section)
		.flatMap((group) => group.items)
		.find((item) => item.label === label)
		.onClick();
}

describe("buildTree and flatten", () => {
	it("nests tabs, sections, columns and fields from the flat list", () => {
		const { tabs } = built();
		expect(tabs.value).toHaveLength(1);
		const [basics, more] = tabs.value[0].sections;
		expect(basics.columns.map((c) => c.fields.length)).toEqual([1, 1]);
		expect(more.columns.map((c) => c.fields.length)).toEqual([1]);
	});

	it("flattens back to the same order, keeping attributes the builder does not show", () => {
		const flat = built().flatten();
		expect(flat.map((f) => f.fieldtype)).toEqual(FIELDS.map((f) => f.fieldtype));
		expect(flat[2].fetch_from).toBe("owner.name");
		expect(flat[2].reqd).toBe(true);
		expect(flat[4].reqd).toBe(false);
	});

	it("creates containers only when a field needs one", () => {
		const tree = built([{ fieldtype: "Data", label: "Solo", fieldname: "solo" }]);
		expect(tree.tabs.value).toHaveLength(1);
		expect(tree.flatten().map((f) => f.fieldname)).toEqual(["solo"]);
	});

	it("always leaves a tab, a section and a column to drop into", () => {
		const tree = built([]);
		expect(tree.tabs.value).toHaveLength(1);
		expect(tree.tabs.value[0].sections[0].columns).toHaveLength(1);
		expect(tree.contentCount.value).toBe(0);
	});

	it("counts only content fields", () => {
		expect(built().contentCount.value).toBe(3);
	});
});

describe("tabs", () => {
	it("adds a tab, makes it active and selects it", () => {
		const tree = built();
		tree.addTab();
		expect(tree.tabs.value).toHaveLength(2);
		expect(tree.activeTabIndex.value).toBe(1);
		expect(tree.sel.type).toBe("tab");
		expect(tree.tabs.value[1].df.fieldtype).toBe("Tab Break");
	});

	it("never removes the last tab", () => {
		const tree = built();
		tree.removeTab(tree.tabs.value[0]);
		expect(tree.tabs.value).toHaveLength(1);
	});

	it("keeps the active index in range after a removal", () => {
		const tree = built();
		tree.addTab();
		tree.removeTab(tree.tabs.value[1]);
		expect(tree.activeTabIndex.value).toBe(0);
		expect(tree.sel.type).toBe("form");
	});

	it("labels unnamed tabs", () => {
		const tree = built([]);
		tree.addTab();
		const [first, second] = tree.tabs.value;
		expect(tree.tabLabel(first, 0)).toBe("Details");
		expect(tree.tabLabel(second, 1)).toBe("Tab 2");
		second.df.label = "Extras";
		expect(tree.tabLabel(second, 1)).toBe("Extras");
	});
});

describe("sections and columns", () => {
	it("adds a section right below the given one", () => {
		const tree = built();
		const [first] = tree.activeTab.value.sections;
		click(tree, first, "Add section below");
		const sections = tree.activeTab.value.sections;
		expect(sections).toHaveLength(3);
		expect(sections[1].df.fieldtype).toBe("Section Break");
		expect(tree.sel.type).toBe("section");
	});

	it("restores an empty section when the last one is removed", () => {
		const tree = built([]);
		click(tree, tree.activeTab.value.sections[0], "Remove section");
		expect(tree.activeTab.value.sections).toHaveLength(1);
	});

	it("moves the last column's fields into the previous one when it is removed", () => {
		const tree = built();
		const [basics] = tree.activeTab.value.sections;
		click(tree, basics, "Remove column");
		expect(basics.columns).toHaveLength(1);
		expect(basics.columns[0].fields).toHaveLength(2);
		expect(tree.sectionMenu(basics).flatMap((g) => g.items.map((i) => i.label))).not.toContain(
			"Remove column",
		);
		expect(basics.columns).toHaveLength(1);
	});

	it("adds a column to a section", () => {
		const tree = built();
		const [, more] = tree.activeTab.value.sections;
		click(tree, more, "Add column");
		expect(more.columns).toHaveLength(2);
		expect(tree.sel.type).toBe("column");
	});

	it("moves a section and the ones after it into a new tab", () => {
		const tree = built();
		const [, more] = tree.activeTab.value.sections;
		click(tree, more, "Move to new tab");
		expect(tree.tabs.value).toHaveLength(2);
		expect(tree.tabs.value[0].sections).toHaveLength(1);
		expect(tree.tabs.value[1].sections).toEqual([more]);
		expect(tree.activeTabIndex.value).toBe(1);
	});

	it("offers menu items that match the section", () => {
		const tree = built();
		const [basics, more] = tree.activeTab.value.sections;
		const labels = (s) => tree.sectionMenu(s).flatMap((g) => g.items.map((i) => i.label));
		expect(labels(basics)).toEqual([
			"Add section below",
			"Remove section",
			"Add column",
			"Remove column",
		]);
		expect(labels(more)).toEqual([
			"Add section below",
			"Remove section",
			"Move to new tab",
			"Add column",
			"Empty column",
		]);
	});

	it("empties the single column of a section but keeps the column", () => {
		const tree = built();
		const [, more] = tree.activeTab.value.sections;
		tree.sectionMenu(more)[1]
			.items.find((i) => i.label === "Empty column")
			.onClick();
		expect(more.columns).toHaveLength(1);
		expect(more.columns[0].fields).toHaveLength(0);
	});

	it("toggles the open menu", () => {
		const tree = built();
		const [basics] = tree.activeTab.value.sections;
		tree.toggleMenu(basics);
		expect(tree.openMenu.value).toBe(basics);
		tree.toggleMenu(basics);
		expect(tree.openMenu.value).toBeNull();
	});
});

describe("fields", () => {
	const firstColumn = (tree) => tree.activeTab.value.sections[0].columns[0];

	it("adds a blank Data field and selects it", () => {
		const tree = built();
		const column = firstColumn(tree);
		tree.addFieldToColumn(column);
		const added = column.fields.at(-1);
		expect(added.df.fieldtype).toBe("Data");
		expect(tree.isSelField(added)).toBe(true);
	});

	it("duplicates a field below itself with an empty name and a Copy label", () => {
		const tree = built();
		const column = firstColumn(tree);
		const original = column.fields[0];
		tree.duplicateField(column, original);
		const copy = column.fields[1];
		expect(copy.df.label).toBe("Title Copy");
		expect(copy.df.fieldname).toBe("");
		expect(copy.df.fetch_from).toBe("owner.name");
	});

	it("adds a field right after the given one", () => {
		const tree = built();
		const column = firstColumn(tree);
		tree.addFieldAfter(column, column.fields[0]);
		expect(column.fields).toHaveLength(2);
		expect(column.fields[1].df.fieldtype).toBe("Data");
	});

	it("clears the selection when the selected field is removed", () => {
		const tree = built();
		const column = firstColumn(tree);
		const field = column.fields[0];
		tree.selectField(field);
		tree.removeField(column, field);
		expect(column.fields).toHaveLength(0);
		expect(tree.sel.type).toBe("form");
	});

	it("splits the fields from a given one into a new column", () => {
		const tree = built([
			{ fieldtype: "Data", label: "A", fieldname: "a" },
			{ fieldtype: "Data", label: "B", fieldname: "b" },
			{ fieldtype: "Data", label: "C", fieldname: "c" },
		]);
		const section = tree.activeTab.value.sections[0];
		const column = section.columns[0];
		tree.moveFieldsToNewColumn(column, column.fields[0]);
		expect(section.columns).toHaveLength(1);
		tree.moveFieldsToNewColumn(column, column.fields[1]);
		expect(section.columns.map((c) => c.fields.length)).toEqual([1, 2]);
	});

	it("names a field from its label unless it is structural or already named", () => {
		const tree = built();
		const df = { fieldtype: "Data", label: " Due Date! ", fieldname: "" };
		tree.autoName(df);
		expect(df.fieldname).toBe("due_date");
		const named = { fieldtype: "Data", label: "Other", fieldname: "keep" };
		tree.autoName(named);
		expect(named.fieldname).toBe("keep");
		const brk = { fieldtype: "Section Break", label: "Break", fieldname: "" };
		tree.autoName(brk);
		expect(brk.fieldname).toBe("");
	});
});

describe("deleteSelected", () => {
	it("deletes a selected field, section, column or tab", () => {
		const tree = built();
		const [basics] = tree.activeTab.value.sections;
		tree.selectField(basics.columns[0].fields[0]);
		tree.deleteSelected();
		expect(basics.columns[0].fields).toHaveLength(0);

		tree.selectContainer("column", basics.columns[1]);
		tree.deleteSelected();
		expect(basics.columns).toHaveLength(1);

		tree.selectContainer("section", basics);
		tree.deleteSelected();
		expect(tree.activeTab.value.sections).toHaveLength(1);

		tree.addTab();
		tree.deleteSelected();
		expect(tree.tabs.value).toHaveLength(1);
		expect(tree.sel.type).toBe("form");
	});
});
