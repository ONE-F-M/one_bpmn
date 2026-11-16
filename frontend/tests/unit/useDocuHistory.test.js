import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { useDocuHistory } from "../../src/composables/Docu/useDocuHistory.js";

function make() {
	const box = { design: { n: 0 } };
	const loadIr = vi.fn((ir) => {
		box.design = ir;
	});
	const history = useDocuHistory({ currentIr: () => box.design, loadIr });
	const record = (n) => {
		box.design = { n };
		history.recordSnapshot();
	};
	return { history, loadIr, record, box };
}

const key = (opts) => ({ preventDefault: vi.fn(), key: "z", ...opts });

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("snapshots", () => {
	it("ignores a snapshot identical to the last one", () => {
		const { history, record } = make();
		record(1);
		record(1);
		expect(history.canUndo.value).toBe(false);
		record(2);
		expect(history.canUndo.value).toBe(true);
	});

	it("keeps at most 60 snapshots", () => {
		const { history, loadIr, record } = make();
		for (let n = 1; n <= 70; n++) record(n);
		let undos = 0;
		while (history.canUndo.value) {
			history.undo();
			undos++;
		}
		expect(undos).toBe(59);
		expect(loadIr).toHaveBeenLastCalledWith({ n: 11 });
	});

	it("drops the redo branch when a new snapshot follows an undo", async () => {
		const { history, record } = make();
		record(1);
		record(2);
		history.undo();
		await nextTick();
		expect(history.canRedo.value).toBe(true);
		record(3);
		expect(history.canRedo.value).toBe(false);
	});

	it("records a pending edit once, 400ms after the last change", () => {
		const { history, box } = make();
		box.design = { n: 1 };
		history.recordSnapshot();
		box.design = { n: 2 };
		history.scheduleSnapshot();
		vi.advanceTimersByTime(300);
		history.scheduleSnapshot();
		vi.advanceTimersByTime(399);
		expect(history.canUndo.value).toBe(false);
		vi.advanceTimersByTime(1);
		expect(history.canUndo.value).toBe(true);
	});

	it("stops a pending snapshot when the timers are stopped", () => {
		const { history, box } = make();
		box.design = { n: 1 };
		history.recordSnapshot();
		box.design = { n: 2 };
		history.scheduleSnapshot();
		history.stopTimers();
		vi.advanceTimersByTime(1000);
		expect(history.canUndo.value).toBe(false);
	});
});

describe("undo and redo", () => {
	it("restores the previous and the next design", () => {
		const { history, loadIr, record } = make();
		record(1);
		record(2);
		history.undo();
		expect(loadIr).toHaveBeenLastCalledWith({ n: 1 });
		history.redo();
		expect(loadIr).toHaveBeenLastCalledWith({ n: 2 });
		expect(history.canRedo.value).toBe(false);
	});

	it("does nothing when there is nothing to undo or redo", () => {
		const { history, loadIr, record } = make();
		history.undo();
		history.redo();
		record(1);
		history.undo();
		history.redo();
		expect(loadIr).not.toHaveBeenCalled();
	});

	it("saves a pending edit before undoing, so the edit can be redone", () => {
		const { history, loadIr, record, box } = make();
		record(1);
		record(2);
		box.design = { n: 3 };
		history.scheduleSnapshot();
		history.undo();
		expect(loadIr).toHaveBeenLastCalledWith({ n: 2 });
		history.redo();
		expect(loadIr).toHaveBeenLastCalledWith({ n: 3 });
	});

	it("does not record snapshots while a restore is settling", async () => {
		const { history, record, box } = make();
		record(1);
		record(2);
		history.undo();
		expect(history.isRestoring()).toBe(true);
		box.design = { n: 99 };
		history.recordSnapshot();
		history.scheduleSnapshot();
		await nextTick();
		expect(history.isRestoring()).toBe(false);
		vi.advanceTimersByTime(1000);
		history.redo();
		expect(box.design).toEqual({ n: 2 });
	});
});

describe("keyboard shortcuts", () => {
	it("undoes on Ctrl+Z and Cmd+Z", () => {
		const { history, loadIr, record } = make();
		record(1);
		record(2);
		record(3);
		const event = key({ ctrlKey: true });
		history.onGlobalKeydown(event);
		history.onGlobalKeydown(key({ metaKey: true }));
		expect(event.preventDefault).toHaveBeenCalled();
		expect(loadIr).toHaveBeenCalledTimes(2);
		expect(loadIr).toHaveBeenLastCalledWith({ n: 1 });
	});

	it("redoes on Ctrl+Shift+Z and Ctrl+Y", () => {
		const { history, loadIr, record } = make();
		record(1);
		record(2);
		record(3);
		history.undo();
		history.undo();
		loadIr.mockClear();
		history.onGlobalKeydown(key({ ctrlKey: true, shiftKey: true }));
		history.onGlobalKeydown(key({ ctrlKey: true, key: "y" }));
		expect(loadIr).toHaveBeenCalledTimes(2);
		expect(loadIr).toHaveBeenLastCalledWith({ n: 3 });
	});

	it("ignores keys without Ctrl or Cmd and other shortcuts", () => {
		const { history, loadIr, record } = make();
		record(1);
		record(2);
		const plain = key({});
		history.onGlobalKeydown(plain);
		history.onGlobalKeydown(key({ ctrlKey: true, key: "x" }));
		expect(plain.preventDefault).not.toHaveBeenCalled();
		expect(loadIr).not.toHaveBeenCalled();
	});
});
