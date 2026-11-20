import { describe, expect, it } from "vitest";
import { createSSRApp, ref } from "vue";
import { renderToString } from "vue/server-renderer";

const { DOCU_KEY } = await import("../../src/composables/Docu/useDocu.js");
const DocuFieldCard = (await import("../../src/components/Docu/DocuFieldCard/DocuFieldCard.vue"))
	.default;

const TABLE_FIELD = {
	df: { fieldname: "items", fieldtype: "Table", label: "Items", options: "Vehicle Item" },
};

async function render(childTables) {
	const app = createSSRApp(DocuFieldCard, {
		fld: TABLE_FIELD,
		column: { fields: [TABLE_FIELD] },
	});
	app.provide(DOCU_KEY, {
		childTables: ref(childTables),
		selectField: () => {},
		isSelField: () => false,
		removeField: () => {},
		duplicateField: () => {},
		addFieldAfter: () => {},
		moveFieldsToNewColumn: () => {},
	});
	// Scoped-style attributes are dropped so the assertions read as plain markup.
	return (await renderToString(app)).replace(/ data-v-\w+/g, "");
}

const column = (label, change, extra = {}) => ({
	fieldname: label.toLowerCase(),
	label,
	fieldtype: "Data",
	reqd: 0,
	options: "",
	change,
	...extra,
});

describe("a child table field in the builder", () => {
	it("opens a changed table and marks each column added, removed or changed", async () => {
		const html = await render([
			{
				fieldname: "items",
				table: "Vehicle Item",
				editable: true,
				note: "",
				columns: [
					column("Part", "added", { reqd: 1 }),
					column("Qty", "changed", { fieldtype: "Int" }),
					column("Supplier", "removed"),
					column("Remark", ""),
				],
			},
		]);
		expect(html).toContain("Hide columns");
		expect(html).toMatch(/text-green-700[^>]*><td>Part<\/td><td>Data<\/td><td>Yes<\/td>/);
		expect(html).toMatch(/text-amber-700[^>]*><td>Qty<\/td><td>Int<\/td>/);
		expect(html).toMatch(/line-through[^>]*><td>Supplier<\/td>/);
		expect(html).toContain("<td>Remark</td>");
	});

	it("keeps an unchanged table closed until it is opened", async () => {
		const html = await render([
			{
				fieldname: "items",
				table: "Vehicle Item",
				editable: true,
				note: "",
				columns: [column("Part", "")],
			},
		]);
		expect(html).toContain("Show 1 columns");
		expect(html).not.toContain("<td>Part</td>");
	});

	it("shows a standard table read-only with its note", async () => {
		const html = await render([
			{
				fieldname: "items",
				table: "Has Role",
				editable: false,
				note: "Has Role is a standard table, so Docu cannot change its columns.",
				columns: [column("Role", "", { fieldtype: "Link", options: "Role" })],
			},
		]);
		expect(html).toContain("Show 1 columns");
		expect(html).not.toContain("Has Role is a standard table");
	});

	it("is a single line when the preview has no columns for it", async () => {
		const html = await render([]);
		expect(html).toContain("Vehicle Item");
		expect(html).not.toContain("columns");
	});
});
