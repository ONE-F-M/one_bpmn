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
	it("sends no app or module until the user picks them, and writes settings as 0/1 and numbers", () => {
		const { ir } = make("  Vehicle ");
		const out = ir.currentIr();
		expect(out.doctype_name).toBe("Vehicle");
		expect(out.app).toBe("");
		expect(out.module).toBe("");
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

const MODULES = [
	{ name: "Processa Engine", app: "processa" },
	{ name: "Stock", app: "erpnext" },
	{ name: "Selling", app: "erpnext" },
];

function withModules(settings) {
	settings.apps.value = ["erpnext", "processa"];
	settings.modules.value = MODULES;
}

describe("app and module", () => {
	it("accepts a module as given until the list has loaded", () => {
		const { settings } = make();
		expect(settings.sanitizeModule("Anything")).toBe("Anything");
		expect(settings.sanitizeModule("")).toBe("");
	});

	it("loads the apps and every module with its app", async () => {
		frappeRequest.mockImplementation(({ url }) =>
			Promise.resolve(url.endsWith("list_apps") ? ["erpnext", "processa"] : MODULES),
		);
		const { settings } = make();
		settings.dtModule.value = "STOCK";
		await settings.loadModules();
		expect(settings.apps.value).toEqual(["erpnext", "processa"]);
		expect(settings.dtModule.value).toBe("Stock");
	});

	it("offers only the picked app's modules", () => {
		const { settings } = make();
		withModules(settings);
		expect(settings.moduleOptions.value).toEqual([]);
		settings.pickApp("erpnext");
		expect(settings.moduleOptions.value).toEqual(["Stock", "Selling"]);
	});

	it("drops a module from another app when the app changes, and keeps one inside it", () => {
		const { settings, onChange } = make();
		withModules(settings);
		settings.pickApp("erpnext");
		settings.dtModule.value = "Stock";
		settings.pickApp("erpnext");
		expect(settings.dtModule.value).toBe("Stock");
		settings.pickApp("processa");
		expect(settings.dtModule.value).toBe("");
		expect(onChange).toHaveBeenCalledTimes(3);
	});

	it("refuses an agent's module outside the picked app or not a module at all", () => {
		const { settings } = make();
		withModules(settings);
		settings.pickApp("processa");
		settings.dtModule.value = "Processa Engine";
		expect(settings.sanitizeModule("stock")).toBe("Processa Engine");
		expect(settings.sanitizeModule("Nope")).toBe("Processa Engine");
		settings.pickApp("erpnext");
		expect(settings.sanitizeModule("stock")).toBe("Stock");
	});

	it("takes the app from a saved doctype and keeps the picked app on an agent turn", () => {
		const { ir, settings } = make();
		withModules(settings);
		ir.loadIr({ doctype_name: "Vehicle", app: "erpnext", module: "Stock", fields: [] });
		expect(ir.currentIr()).toMatchObject({ app: "erpnext", module: "Stock" });
		ir.loadIr({ doctype_name: "Vehicle", module: "Selling", fields: [] });
		expect(ir.currentIr()).toMatchObject({ app: "erpnext", module: "Selling" });
	});

	it("ignores a failed or malformed list", async () => {
		const { settings } = make();
		frappeRequest.mockRejectedValueOnce(new Error("no"));
		await settings.loadModules();
		frappeRequest.mockResolvedValue({ not: "a list" });
		await settings.loadModules();
		expect(settings.modules.value).toEqual([]);
		expect(settings.apps.value).toEqual([]);
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

	it("reloads after a turn only when the saved doctype changed on the server", async () => {
		const schema = (modified, label) => ({
			exists: true,
			modified,
			doctype_ir: {
				doctype_name: "Vehicle",
				fields: [{ fieldtype: "Data", label, fieldname: "plate" }],
			},
		});
		const { ir } = make();
		frappeRequest.mockResolvedValueOnce(schema("t1", "Plate"));
		await ir.loadSchema("Vehicle");

		frappeRequest.mockResolvedValueOnce(schema("t1", "Ignored"));
		await ir.reloadIfChangedElsewhere("Vehicle");
		expect(ir.currentIr().fields[0].label).toBe("Plate");

		frappeRequest.mockResolvedValueOnce(schema("t2", "Plate No"));
		await ir.reloadIfChangedElsewhere("Vehicle");
		expect(ir.currentIr().fields[0].label).toBe("Plate No");
		expect(ir.baseModified.value).toBe("t2");
	});

	it("passes a failed reload to the caller", async () => {
		const { ir } = make();
		frappeRequest.mockResolvedValueOnce({ exists: true, modified: "t1", doctype_ir: { fields: [] } });
		await ir.loadSchema("Vehicle");
		frappeRequest.mockRejectedValueOnce(new Error("offline"));
		await expect(ir.reloadIfChangedElsewhere("Vehicle")).rejects.toThrow("offline");
	});

	it("does not reload a doctype that was never saved", async () => {
		const { ir } = make();
		await ir.reloadIfChangedElsewhere("Fresh");
		expect(frappeRequest).not.toHaveBeenCalled();
	});
});
