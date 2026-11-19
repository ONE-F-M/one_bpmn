import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }));

const { frappeRequest } = await import("frappe-ui");
const { useDocuChat } = await import("../../src/composables/Docu/useDocuChat.js");

const API = "/api/method/processa.api.docu.";
const IR = { doctype_name: "Vehicle", fields: [] };

function make(props = {}, names = {}) {
	const autosave = {
		saveNotes: ref(""),
		childChanges: ref([]),
		childTables: ref([]),
		saveError: ref(""),
		saveState: ref("idle"),
	};
	const loadIr = vi.fn();
	const baseModified = ref("2026-11-19 10:00:00");
	const chat = useDocuChat({
		props: { doctype: "", processContext: null, ...props },
		dtName: ref(names.dtName || ""),
		dtApp: ref(names.dtApp || ""),
		dtModule: ref(names.dtModule || ""),
		loadIr,
		baseModified,
		autosave,
	});
	return { chat, autosave, loadIr, baseModified };
}

beforeEach(() => {
	frappeRequest.mockReset();
	vi.stubGlobal(
		"DOMParser",
		class {
			parseFromString(text) {
				return { body: { textContent: text } };
			}
		},
	);
});

afterEach(() => vi.unstubAllGlobals());

describe("turn context", () => {
	it("names the doctype being built, else the one on the shape, else nothing", () => {
		expect(make({}, { dtName: "Draft" }).chat.docuTurnContext.value.doctype).toBe("Draft");
		expect(make({ doctype: "Vehicle" }).chat.docuTurnContext.value.doctype).toBe("Vehicle");
		expect(make().chat.docuTurnContext.value.doctype).toBe("");
	});

	it("carries the target app, module and the process context", () => {
		const processContext = { process: "Fleet Check" };
		const { chat } = make({ processContext }, { dtApp: "erpnext", dtModule: "Stock" });
		expect(chat.docuTurnContext.value).toEqual({
			doctype: "",
			target_app: "erpnext",
			target_module: "Stock",
			process_context: processContext,
		});
	});

	it("greets by doctype only when the shape already has one", () => {
		expect(make().chat.hostContextLine.value).toBe("");
		expect(make({ doctype: "Vehicle" }).chat.hostContextLine.value).toContain("**Vehicle**");
	});
});

describe("schema cards", () => {
	it("loads the IR and lists what the change does to child tables", async () => {
		frappeRequest.mockResolvedValue({
			child_changes: [{ table: "Items", lines: ["Add row", "Drop column"] }],
			warnings: ["Heads up"],
		});
		const { chat, autosave, loadIr } = make();
		chat.onDocuCardAction({
			name: "onefm.doctype_schema",
			action: "apply-schema",
			value: { doctype_ir: IR },
		});
		expect(loadIr).toHaveBeenCalledWith(IR);
		await vi.waitFor(() => expect(autosave.childChanges.value).toHaveLength(2));
		expect(autosave.childChanges.value).toEqual(["Items: Add row Drop column", "Heads up"]);
		expect(frappeRequest.mock.calls[0][0]).toEqual({
			url: `${API}preview_doctype`,
			params: { ir: JSON.stringify(IR) },
		});
	});

	it("saves a card on the copy it was built from, so an older card cannot overwrite a newer save", () => {
		frappeRequest.mockResolvedValue({});
		const { chat, baseModified } = make();
		chat.onDocuCardAction({
			name: "onefm.doctype_schema",
			action: "apply-schema",
			value: { doctype_ir: IR, base_modified: "2026-11-19 09:00:00" },
		});
		expect(baseModified.value).toBe("2026-11-19 09:00:00");
		chat.onDocuCardAction({
			name: "onefm.doctype_schema",
			action: "apply-schema",
			value: { doctype_ir: IR },
		});
		expect(baseModified.value).toBe("2026-11-19 09:00:00");
	});

	it("keeps the columns of each child table from the preview", async () => {
		const table = {
			fieldname: "items",
			table: "Vehicle Item",
			columns: [{ label: "Part", change: "added" }],
		};
		frappeRequest.mockResolvedValue({ child_tables_preview: [table] });
		const { chat, autosave } = make();
		await chat.loadChildChanges(IR);
		expect(autosave.childTables.value).toEqual([table]);
	});

	it("shows an error when the preview fails", async () => {
		frappeRequest.mockRejectedValue({ messages: ["Bad IR"] });
		const { chat, autosave } = make();
		chat.onDocuCardAction({
			name: "onefm.doctype_schema",
			action: "apply-schema",
			value: { doctype_ir: IR },
		});
		await vi.waitFor(() => expect(autosave.saveState.value).toBe("error"));
		expect(autosave.saveError.value).toBe("Bad IR");
		expect(autosave.childChanges.value).toEqual([]);
	});

	it("ignores a schema card without an IR, and other cards", () => {
		const { chat, loadIr } = make();
		chat.onDocuCardAction({ name: "onefm.doctype_schema", action: "apply-schema", value: {} });
		chat.onDocuCardAction({
			name: "other",
			action: "apply-schema",
			value: { doctype_ir: IR },
		});
		chat.onDocuCardAction({
			name: "onefm.doctype_schema",
			action: "dismiss",
			value: { doctype_ir: IR },
		});
		expect(loadIr).not.toHaveBeenCalled();
		expect(frappeRequest).not.toHaveBeenCalled();
	});
});

describe("script cards", () => {
	const card = {
		name: "onefm.script_diff",
		action: "apply-script",
		value: { apply_target: "Vehicle", modified_script: "frappe.ui.form.on('Vehicle', {});" },
	};

	it("posts the script to the doctype and keeps the server's note", async () => {
		frappeRequest.mockResolvedValue("Script saved.");
		const { chat, autosave } = make();
		chat.onDocuCardAction({ ...card, fail: vi.fn() });
		await vi.waitFor(() => expect(autosave.saveNotes.value).toBe("Script saved."));
		expect(frappeRequest.mock.calls[0][0]).toEqual({
			url: `${API}apply_client_script`,
			method: "POST",
			params: { doctype: "Vehicle", script: card.value.modified_script },
		});
	});

	it("hands the server's message to the card when the script is refused", async () => {
		frappeRequest.mockRejectedValue({ messages: ["Not allowed"] });
		const fail = vi.fn();
		const { chat } = make();
		chat.onDocuCardAction({ ...card, fail });
		await vi.waitFor(() => expect(fail).toHaveBeenCalledWith("Not allowed"));
	});
});
