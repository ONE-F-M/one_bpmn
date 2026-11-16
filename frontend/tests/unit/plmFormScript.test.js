import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import vm from "node:vm";
import { describe, expect, it, vi } from "vitest";

const SCRIPT = readFileSync(
	resolve(
		__dirname,
		"../../../processa/processa_engine/doctype/processa_legacy_migration/processa_legacy_migration.js",
	),
	"utf8",
);
const PROGRESS = "legacy_migration_progress";

function loadForm(roles, model = {}) {
	const handlers = {};
	const listeners = new Map();
	const frappe = {
		ui: { form: { on: (_doctype, events) => Object.assign(handlers, events) } },
		user: { has_role: (role) => roles.includes(role) },
		session: { user: "owner@example.com" },
		db: {
			get_list: vi.fn(async () => [{ name: "PLM Test" }]),
			get_doc: vi.fn(async () => model),
		},
		realtime: {
			on: (event, fn) => listeners.set(event, [...(listeners.get(event) || []), fn]),
			off: (event) => listeners.delete(event),
		},
	};
	const translate = (text, args = []) => text.replace(/\{(\d)\}/g, (_match, i) => args[i]);
	vm.runInNewContext(SCRIPT, { frappe, __: translate, setTimeout: () => {} });
	return { handlers, listeners, frappe };
}

function makeFrm(doc = {}) {
	const headlines = [];
	return {
		doc: { name: "PLM-0001", status: "Running", ...doc },
		headlines,
		set_query: vi.fn(),
		set_value: vi.fn(),
		clear_table: vi.fn(),
		refresh_field: vi.fn(),
		disable_save: vi.fn(),
		set_read_only: vi.fn(),
		reload_doc: vi.fn(),
		dashboard: {
			clear_headline: () => headlines.splice(0),
			set_headline: (text) => headlines.push(text),
		},
	};
}

describe("Processa Legacy Migration form", () => {
	it("limits both map pickers to the Process Owner's processes", async () => {
		const { handlers, frappe } = loadForm(["Process Owner"]);
		const frm = makeFrm();
		handlers.setup(frm);
		await vi.waitFor(() => expect(frm.set_query).toHaveBeenCalledTimes(2));
		expect(frappe.db.get_list.mock.calls[0][1].filters).toEqual({
			process_owner: "owner@example.com",
		});
		for (const [fieldname, query] of frm.set_query.mock.calls) {
			expect(["from_model", "to_model"]).toContain(fieldname);
			expect(query().filters).toEqual({ process_name: ["in", ["PLM Test"]] });
		}
	});

	it("leaves the pickers open for a System Manager", () => {
		const { handlers, frappe } = loadForm(["System Manager"]);
		const frm = makeFrm();
		handlers.setup(frm);
		expect(frappe.db.get_list).not.toHaveBeenCalled();
		expect(frm.set_query).not.toHaveBeenCalled();
	});

	it("fills Target DocType from a new map that runs on one DocType", async () => {
		const { handlers } = loadForm(["System Manager"], {
			target_doctypes: [{ doctype_name: "GP Letter Request" }],
		});
		const frm = makeFrm({ to_model: "PLM Demo - v2" });
		handlers.to_model(frm);
		await vi.waitFor(() =>
			expect(frm.set_value).toHaveBeenCalledWith("target_doctype", "GP Letter Request"),
		);
	});

	it("clears Target DocType and offers only the map's DocTypes when it runs on several", async () => {
		const model = {
			target_doctypes: [{ doctype_name: "GP Letter Request" }, { doctype_name: "Note" }],
		};
		const { handlers } = loadForm(["System Manager"], model);
		const frm = makeFrm({ to_model: "PLM Demo - v2" });
		handlers.to_model(frm);
		await vi.waitFor(() => expect(frm.set_query).toHaveBeenCalled());
		expect(frm.set_value).toHaveBeenCalledWith("target_doctype", "");
		const [fieldname, query] = frm.set_query.mock.calls[0];
		expect(fieldname).toBe("target_doctype");
		expect(query().filters).toEqual({ name: ["in", ["GP Letter Request", "Note"]] });
	});

	it("clears the state mapping when the old map changes", () => {
		const { handlers } = loadForm(["System Manager"]);
		const frm = makeFrm();
		handlers.from_model(frm);
		expect(frm.clear_table).toHaveBeenCalledWith("state_map");
	});

	it("keeps one progress listener however often the form opens", () => {
		const { handlers, listeners } = loadForm(["System Manager"]);
		const frm = makeFrm();
		handlers.onload(frm);
		handlers.onload(frm);
		expect(listeners.get(PROGRESS)).toHaveLength(1);
	});

	it("replaces the headline on each progress event and shows the batches", () => {
		const { handlers, listeners } = loadForm(["System Manager"]);
		const frm = makeFrm();
		handlers.onload(frm);
		const [onProgress] = listeners.get(PROGRESS);
		const event = {
			migration_name: "PLM-0001",
			migrated: 3,
			failed: 1,
			total: 30,
			total_batches: 2,
		};
		onProgress({ ...event, batches_done: 1 });
		onProgress({ ...event, batches_done: 2 });
		expect(frm.headlines).toEqual([
			"Migration is Running. Migrated: 3 | Failed: 1 | Total: 30 | Batches Done: 2 of 2",
		]);
	});
});
