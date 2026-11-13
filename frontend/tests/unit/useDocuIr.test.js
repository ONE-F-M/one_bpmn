import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }));

const { frappeRequest } = await import("frappe-ui");
const { useDocuIr } = await import("../../src/composables/Docu/useDocuIr.js");
const { useDocuSettings } = await import("../../src/composables/Docu/useDocuSettings.js");
const { useDocuTree } = await import("../../src/composables/Docu/useDocuTree.js");

function make(doctype = "") {
	const onChange = vi.fn();
	const settings = useDocuSettings({ doctype, onChange });
	const tree = useDocuTree();
	const ir = useDocuIr({ tree, settings });
	return { settings, tree, ir, onChange };
}

afterEach(() => {
	frappeRequest.mockReset();
	vi.restoreAllMocks();
});

describe("currentIr", () => {
	it("falls back to the default module and writes settings as 0/1 and numbers", () => {
		const { ir, settings } = make("  Vehicle ");
		settings.dtModule.value = "";
		const out = ir.currentIr();
		expect(out.doctype_name).toBe("Vehicle");
		expect(out.module).toBe("ONE BPMN");
		expect(out.is_child_table).toBe(false);
		expect(out.is_submittable).toBe(0);
		expect(out.editable_grid).toBe(1);
		expect(out.max_attachments).toBe(0);
		expect(out.sort_order).toBe("DESC");
	});

	it("drops permission rules without a role and normalises the rest", () => {
		const { ir, settings } = make("Vehicle");
		settings.permissions.value = [
			{ role: "  Fleet Manager ", read: true, write: 0, permlevel: "1" },
			{ role: "   ", read: 1 },
		];
		const { permissions } = ir.currentIr();
		expect(permissions).toHaveLength(1);
		expect(permissions[0]).toMatchObject({
			role: "Fleet Manager",
			permlevel: 1,
			read: 1,
			write: 0,
			create: 0,
		});
	});

	it("serialises fields with flags as 0/1, structural names emptied and options trimmed", () => {
		const { ir, tree } = make("Vehicle");
		tree.buildTree([
			{ fieldtype: "Section Break", label: "Basics", fieldname: "ignored" },
			{
				fieldtype: "Select",
				label: "Kind",
				fieldname: " kind ",
				options: " A\nB ",
				reqd: true,
			},
			{ fieldtype: "Data", label: "Plate", fieldname: "plate", fetch_from: "owner.plate" },
		]);
		const fields = ir.currentIr().fields;
		expect(fields[0]).toMatchObject({ fieldtype: "Section Break", fieldname: "" });
		expect(fields[1]).toMatchObject({ fieldname: "kind", options: "A\nB", reqd: 1 });
		expect(fields[2]).toMatchObject({ reqd: 0, fetch_from: "owner.plate" });
	});
});

describe("loadIr", () => {
	it("round-trips the design it produced", () => {
		const { ir } = make("Vehicle");
		ir.loadIr({
			doctype_name: "Vehicle",
			module: "Stock",
			is_submittable: 1,
			sort_order: "ASC",
			max_attachments: "4",
			permissions: [{ role: "Fleet Manager", read: 1 }],
			fields: [
				{ fieldtype: "Data", label: "Plate", fieldname: "plate" },
				{ fieldtype: "Column Break" },
				{ fieldtype: "Int", label: "Seats", fieldname: "seats", reqd: 1 },
			],
		});
		const first = ir.currentIr();
		ir.loadIr(first);
		expect(ir.currentIr()).toEqual(first);
		expect(first.max_attachments).toBe(4);
		expect(first.is_submittable).toBe(1);
	});

	it("leaves settings and permissions alone when the IR does not carry them", () => {
		const { ir, settings } = make("Vehicle");
		settings.dtSettings.is_submittable = true;
		settings.permissions.value = [{ role: "Fleet Manager", read: 1 }];
		ir.loadIr({ fields: [{ fieldtype: "Data", label: "Plate", fieldname: "plate" }] });
		expect(settings.dtSettings.is_submittable).toBe(true);
		expect(settings.permissions.value).toHaveLength(1);
		expect(ir.currentIr().fields).toHaveLength(1);
	});

	it("replaces permissions when the IR carries a list, even an empty one", () => {
		const { ir, settings } = make("Vehicle");
		settings.permissions.value = [{ role: "Fleet Manager", read: 1 }];
		ir.loadIr({ permissions: [] });
		expect(settings.permissions.value).toEqual([]);
	});

	it("clears the applied name and selects the form", () => {
		const { ir, tree } = make("Vehicle");
		ir.appliedName.value = "Vehicle";
		ir.applyError.value = "boom";
		tree.sel.type = "field";
		ir.loadIr({ fields: [] });
		expect(ir.appliedName.value).toBe("");
		expect(ir.applyError.value).toBe("");
		expect(tree.sel.type).toBe("form");
	});

	it("ignores an empty IR", () => {
		const { ir, settings } = make("Vehicle");
		ir.loadIr(null);
		expect(settings.dtName.value).toBe("Vehicle");
	});
});

describe("module matching", () => {
	it("accepts a module as given until the list has loaded", () => {
		const { settings } = make();
		expect(settings.sanitizeModule("Anything")).toBe("Anything");
		expect(settings.sanitizeModule("")).toBe("ONE BPMN");
	});

	it("normalises a module to the spelling of the Module Def", async () => {
		frappeRequest.mockResolvedValue(["ONE BPMN", "Stock"]);
		const { settings } = make();
		await settings.loadModules();
		expect(settings.sanitizeModule("stock")).toBe("Stock");
	});

	it("keeps the current module and warns when the name is not a module", async () => {
		const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
		frappeRequest.mockResolvedValue(["ONE BPMN", "Stock"]);
		const { settings } = make();
		await settings.loadModules();
		expect(settings.sanitizeModule("Nope")).toBe("ONE BPMN");
		expect(warn).toHaveBeenCalledOnce();
	});

	it("normalises a module set before the list arrived", async () => {
		frappeRequest.mockResolvedValue(["ONE BPMN", "Stock"]);
		const { settings } = make();
		settings.dtModule.value = "STOCK";
		await settings.loadModules();
		expect(settings.dtModule.value).toBe("Stock");
	});

	it("ignores a failed or malformed module list", async () => {
		const { settings } = make();
		frappeRequest.mockRejectedValueOnce(new Error("no"));
		await settings.loadModules();
		frappeRequest.mockResolvedValueOnce({ not: "a list" });
		await settings.loadModules();
		expect(settings.modules.value).toEqual([]);
	});

	it("always offers the current module and the default one", () => {
		const { settings } = make();
		settings.modules.value = ["Stock"];
		settings.dtModule.value = "Custom";
		expect(settings.moduleOptions.value).toEqual(["ONE BPMN", "Custom", "Stock"]);
	});
});

describe("settings", () => {
	it("keeps a role the agent named selectable before the list arrives", async () => {
		const { settings } = make();
		expect(settings.roleOptions("Fleet Manager")).toEqual(["Fleet Manager"]);
		frappeRequest.mockResolvedValue(["Employee"]);
		await settings.loadRoles();
		expect(settings.roleOptions("Fleet Manager")).toEqual(["Fleet Manager", "Employee"]);
		expect(settings.roleOptions("Employee")).toEqual(["Employee"]);
	});

	it("starts a new permission rule as plain read access and reports the change", () => {
		const { settings, onChange } = make();
		settings.addPermission();
		expect(settings.permissions.value[0]).toMatchObject({ role: "", read: 1, write: 0 });
		settings.removePermission(0);
		expect(settings.permissions.value).toEqual([]);
		expect(onChange).toHaveBeenCalledTimes(2);
	});

	it("shows the child-table settings only for a child table", () => {
		const { settings } = make();
		const keys = () =>
			settings.settingsSections.value.flatMap((s) =>
				(s.show === false ? [] : s.fields)
					.filter((f) => f.show !== false)
					.map((f) => f.key),
			);
		expect(keys()).toContain("is_submittable");
		expect(keys()).not.toContain("editable_grid");
		settings.isChild.value = true;
		expect(keys()).toContain("editable_grid");
		expect(keys()).not.toContain("is_submittable");
	});
});

describe("loadSchema", () => {
	it("loads the schema of an existing doctype", async () => {
		frappeRequest.mockResolvedValue({
			exists: true,
			doctype_ir: {
				doctype_name: "Vehicle",
				fields: [{ fieldtype: "Data", label: "Plate", fieldname: "plate" }],
			},
		});
		const { ir } = make();
		await ir.loadSchema("Vehicle");
		expect(frappeRequest.mock.calls[0][0]).toEqual({
			url: "/api/method/processa.api.docu.get_doctype_schema",
			params: { doctype: "Vehicle" },
		});
		expect(ir.currentIr().fields).toHaveLength(1);
	});

	it("leaves a new doctype empty, and swallows a failed lookup", async () => {
		const { ir, settings } = make();
		frappeRequest.mockResolvedValueOnce({ exists: false });
		await ir.loadSchema("Fresh");
		frappeRequest.mockRejectedValueOnce(new Error("no"));
		await ir.loadSchema("Fresh");
		expect(settings.dtName.value).toBe("");
	});
});
