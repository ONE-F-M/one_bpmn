import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }));
vi.mock("@iconify/vue", () => ({ Icon: { render: () => null } }));
vi.mock("@/components/Chat/AgentChatPanel/AgentChatPanel.vue", () => ({ default: { render: () => null } }));
vi.mock("@/utils/cardRegistry", () => ({ cardRegistry: {} }));
vi.mock("@/components/Docu/DocuFormCanvas/DocuFormCanvas.vue", () => ({
	default: { render: () => null },
}));
vi.mock("@/components/Docu/DocuSettingsView/DocuSettingsView.vue", () => ({
	default: { render: () => null },
}));
vi.mock("@/components/Docu/DocuPropertiesPanel/DocuPropertiesPanel.vue", () => ({
	default: { render: () => null },
}));
vi.mock("@/components/Docu/DocuChangesPreview/DocuChangesPreview.vue", () => ({
	default: { render: () => null },
}));
vi.mock("@/components/Docu/DocuApplyBar/DocuApplyBar.vue", async () => {
	const { useDocu } = await import("@/composables/useDocu");
	return {
		default: {
			setup() {
				globalThis.__docuState = useDocu();
				return () => null;
			},
		},
	};
});

const { createRenderer } = await import("vue");
const { frappeRequest } = await import("frappe-ui");
const DocuCanvas = (await import("../../src/components/Docu/DocuCanvas/DocuCanvas.vue")).default;

// A renderer that builds plain objects, so the real shell can mount without a DOM.
const { createApp } = createRenderer({
	createElement: (tag) => ({
		tag,
		style: {},
		children: [],
		value: "",
		addEventListener: () => {},
		removeEventListener: () => {},
	}),
	createText: (text) => ({ text }),
	createComment: (text) => ({ comment: text }),
	setText: () => {},
	setElementText: () => {},
	insert: (child, parent) => {
		child.parent = parent;
	},
	remove: () => {},
	parentNode: (node) => node.parent || null,
	nextSibling: () => null,
	querySelector: () => ({ tag: "body", style: {}, children: [] }),
	patchProp: () => {},
});

const API = "/api/method/one_bpmn.api.docu_api.";
const saves = () => frappeRequest.mock.calls.filter(([r]) => r.url === `${API}apply_doctype`);
const flush = async () => {
	for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(0);
};
const PLATE = [{ fieldtype: "Data", label: "Plate", fieldname: "plate" }];

let listeners;

async function mountCanvas() {
	const app = createApp(DocuCanvas, { doctype: "", open: true });
	app.mount({});
	await flush();
	return { app, state: globalThis.__docuState };
}

beforeEach(() => {
	vi.useFakeTimers();
	listeners = [];
	vi.stubGlobal("window", {
		addEventListener: vi.fn((...args) => listeners.push(["add", ...args])),
		removeEventListener: vi.fn((...args) => listeners.push(["remove", ...args])),
	});
	vi.stubGlobal("document", { body: { classList: { add: vi.fn(), remove: vi.fn() } } });
	frappeRequest.mockReset();
	frappeRequest.mockImplementation(async ({ url }) => {
		if (url.endsWith("can_change_forms")) return true;
		if (url.endsWith("apply_doctype")) return { name: "Vehicle" };
		return [];
	});
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	globalThis.__docuState = undefined;
});

describe("DocuCanvas lifecycle", () => {
	it("saves an edit made while the canvas is open", async () => {
		const { state } = await mountCanvas();
		state.dtName.value = "Vehicle";
		state.buildTree(PLATE);
		await flush();
		await vi.advanceTimersByTimeAsync(1500);
		expect(saves()).toHaveLength(1);
	});

	it("saves nothing once the canvas is unmounted", async () => {
		const { app, state } = await mountCanvas();
		app.unmount();
		state.dtName.value = "Vehicle";
		state.buildTree(PLATE);
		await flush();
		await vi.advanceTimersByTimeAsync(5000);
		expect(saves()).toHaveLength(0);
	});

	it("takes its shortcuts and page class away when it unmounts", async () => {
		const { app } = await mountCanvas();
		expect(document.body.classList.add).toHaveBeenCalledWith("docu-open");
		app.unmount();
		expect(document.body.classList.remove).toHaveBeenCalledWith("docu-open");
		const keydown = listeners.filter(([, name]) => name === "keydown");
		expect(keydown.map(([kind]) => kind)).toEqual(["add", "remove"]);
	});
});
