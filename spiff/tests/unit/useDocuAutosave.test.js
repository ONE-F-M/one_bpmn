import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }));

const { frappeRequest } = await import("frappe-ui");
const { useDocuAutosave } = await import("../../src/composables/Docu/useDocuAutosave.js");

const API = "/api/method/one_bpmn.api.docu_api.";
const IR = { doctype_name: "Vehicle", fields: [] };
let store;

function make(overrides = {}) {
	const parts = {
		dtName: ref("Vehicle"),
		contentCount: ref(1),
		currentIr: () => IR,
		appliedName: ref(""),
		loadIr: vi.fn(),
		isRestoring: () => false,
		getProcessContext: () => ({ process: "Fleet Check" }),
		emit: vi.fn(),
		...overrides,
	};
	const autosave = useDocuAutosave(parts);
	autosave.canChange.value = true;
	return { autosave, ...parts };
}

const saves = () => frappeRequest.mock.calls.filter(([r]) => r.url === `${API}apply_doctype`);

beforeEach(() => {
	vi.useFakeTimers();
	store = new Map();
	vi.stubGlobal("localStorage", {
		getItem: (k) => (store.has(k) ? store.get(k) : null),
		setItem: (k, v) => store.set(k, String(v)),
		removeItem: (k) => store.delete(k),
	});
	vi.stubGlobal(
		"DOMParser",
		class {
			parseFromString(text) {
				return { body: { textContent: text } };
			}
		},
	);
	frappeRequest.mockReset();
	frappeRequest.mockResolvedValue({ name: "Vehicle", notes: ["Added a field."] });
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

describe("debounce", () => {
	it("saves once, 1.5 seconds after the last change", async () => {
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1000);
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1499);
		expect(saves()).toHaveLength(0);
		await vi.advanceTimersByTimeAsync(1);
		expect(saves()).toHaveLength(1);
	});

	it("does not schedule a save while a restore is settling", async () => {
		const { autosave } = make({ isRestoring: () => true });
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(5000);
		expect(saves()).toHaveLength(0);
	});

	it("drops a pending save when the timers are stopped", async () => {
		const { autosave } = make();
		autosave.scheduleAutosave();
		autosave.stopTimers();
		await vi.advanceTimersByTimeAsync(5000);
		expect(saves()).toHaveLength(0);
	});

	it("saves only a valid design the user may change", async () => {
		const noRights = make();
		noRights.autosave.canChange.value = false;
		noRights.autosave.scheduleAutosave();
		const noName = make({ dtName: ref("  ") });
		noName.autosave.scheduleAutosave();
		const noFields = make({ contentCount: ref(0) });
		noFields.autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(2000);
		expect(saves()).toHaveLength(0);
	});
});

describe("saving", () => {
	it("sends the design with confirm and the process", async () => {
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(saves()[0][0]).toEqual({
			url: `${API}apply_doctype`,
			method: "POST",
			params: {
				ir: JSON.stringify(IR),
				confirm: 1,
				process: "Fleet Check",
				list_in_process: undefined,
			},
		});
	});

	it("reports the saved name, keeps the notes and clears an unsaved copy", async () => {
		const { autosave, appliedName, emit } = make();
		store.set("docu-unsaved:Vehicle", "old");
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.saveState.value).toBe("saved");
		expect(appliedName.value).toBe("Vehicle");
		expect(emit).toHaveBeenCalledWith("applied", "Vehicle");
		expect(autosave.saveNotes.value).toBe("Added a field.");
		expect(store.has("docu-unsaved:Vehicle")).toBe(false);
	});

	it("asks whether to list the doctype and saves again with the answer", async () => {
		frappeRequest.mockResolvedValueOnce({
			status: "needs_listing_decision",
			message: "List it?",
		});
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.saveState.value).toBe("question");
		expect(autosave.listingQuestion.value).toBe("List it?");
		autosave.answerListing(true);
		await vi.advanceTimersByTimeAsync(0);
		expect(saves()[1][0].params.list_in_process).toBe(1);
		expect(autosave.listingQuestion.value).toBe("");
		autosave.answerListing(false);
		await vi.advanceTimersByTimeAsync(0);
		expect(saves()[2][0].params.list_in_process).toBe(0);
	});

	it("shows a pending approval with a link to the change request", async () => {
		frappeRequest.mockResolvedValueOnce({
			status: "pending_approval",
			message: "Waiting on DCR-001 for review.",
			request: "DCR-001",
		});
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.saveState.value).toBe("pending");
		expect(autosave.pendingParts.value).toEqual({
			before: "Waiting on ",
			after: " for review.",
		});
		expect(autosave.pendingUrl.value).toBe("/app/doctype-change-request/DCR-001");
	});

	it("has no pending link when the request is not in the notice", async () => {
		frappeRequest.mockResolvedValueOnce({
			status: "pending_approval",
			message: "Waiting.",
			request: "DCR-002",
		});
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.pendingParts.value).toBeNull();
	});

	it("keeps the design in this browser when the save fails", async () => {
		frappeRequest.mockRejectedValueOnce({ messages: ["Name taken"] });
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.saveState.value).toBe("error");
		expect(autosave.saveError.value).toBe("Name taken");
		expect(store.get("docu-unsaved:Vehicle")).toBe(JSON.stringify(IR));
	});

	it("says so when the browser will not keep the unsaved design", async () => {
		vi.stubGlobal("localStorage", {
			getItem: () => {
				throw new Error("blocked");
			},
			setItem: () => {
				throw new Error("blocked");
			},
			removeItem: () => {
				throw new Error("blocked");
			},
		});
		frappeRequest.mockRejectedValueOnce({ messages: ["Name taken"] });
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.saveNotes.value).toBe(
			"This browser does not allow Docu to keep an unsaved design.",
		);
		expect(autosave.readUnsaved()).toBeNull();
	});

	it("queues a change made during a save and saves again afterwards", async () => {
		let finish;
		frappeRequest.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					finish = resolve;
				}),
		);
		const { autosave } = make();
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(autosave.saveState.value).toBe("saving");
		autosave.scheduleAutosave();
		await vi.advanceTimersByTimeAsync(1500);
		expect(saves()).toHaveLength(1);
		finish({ name: "Vehicle" });
		await vi.advanceTimersByTimeAsync(0);
		expect(saves()).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(1500);
		expect(saves()).toHaveLength(2);
	});
});

describe("restore and rights", () => {
	it("hands the unsaved design back to the builder", () => {
		const { autosave, loadIr } = make();
		autosave.unsavedDesign.value = JSON.stringify(IR);
		autosave.restoreUnsavedDesign();
		expect(loadIr).toHaveBeenCalledWith(IR);
		expect(autosave.unsavedDesign.value).toBe("");
	});

	it("reads whether the user may change forms, and says no on failure", async () => {
		const { autosave } = make();
		frappeRequest.mockResolvedValueOnce(true);
		await autosave.loadCanChange();
		expect(autosave.canChange.value).toBe(true);
		frappeRequest.mockRejectedValueOnce(new Error("no"));
		await autosave.loadCanChange();
		expect(autosave.canChange.value).toBe(false);
		frappeRequest.mockResolvedValueOnce(0);
		await autosave.loadCanChange();
		expect(autosave.canChange.value).toBe(false);
	});
});
