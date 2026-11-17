import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Each Button stub keeps its click handler under its label, so a test can press it.
vi.mock("frappe-ui", async () => {
	const { h } = await import("vue");
	const stub = {
		setup:
			(_, { slots }) =>
			() =>
				h("span", slots.default?.()),
	};
	const button = {
		setup: (_, { slots, attrs }) => {
			const label = slots.default?.()?.[0]?.children?.trim();
			if (label) globalThis.__buttons[label] = attrs.onClick;
			return () => h("span", slots.default?.());
		},
	};
	return {
		Badge: stub,
		Button: button,
		Dialog: stub,
		ErrorMessage: stub,
		FormControl: stub,
		frappeRequest: vi.fn(),
	};
});

// Node has no DOMParser; this one strips tags, which is all these cases need.
globalThis.DOMParser ??= class {
	parseFromString(html) {
		return { body: { textContent: html.replace(/<[^>]*>/g, "") } };
	}
};

const { createRenderer } = await import("vue");
const { frappeRequest } = await import("frappe-ui");
const A2ARemoteAgents = (
	await import("../../src/components/A2A/A2ARemoteAgents/A2ARemoteAgents.vue")
).default;

const texts = [];

// A renderer that builds plain objects and keeps every text it is given, so the component can mount without a DOM.
const { createApp } = createRenderer({
	createElement: (tag) => ({ tag, children: [] }),
	createText: (text) => {
		texts.push(text);
		return { text };
	},
	createComment: (text) => ({ comment: text }),
	setText: (_, text) => texts.push(text),
	setElementText: (_, text) => texts.push(text),
	insert: (child, parent) => {
		child.parent = parent;
	},
	remove: () => {},
	parentNode: (node) => node.parent || null,
	nextSibling: () => null,
	patchProp: () => {},
});

const REMOTE = {
	name: "BA Agent",
	agent_name: "BA Agent",
	endpoint_url: "https://ba.example",
	approval_status: "Draft",
};
const flush = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
};

let errors;

beforeEach(() => {
	globalThis.__buttons = {};
	errors = [];
	texts.length = 0;
	frappeRequest.mockReset();
});

afterEach(() => {
	delete globalThis.__buttons;
});

describe("the remote agents tab", () => {
	it("shows the server's message when a card cannot be fetched", async () => {
		const failure = Object.assign(
			new Error("/api/method/processa.api.a2a_admin.fetch_remote_card A2AClientError"),
			{
				messages: [
					"Could not fetch an agent card from https://ba.example: 403 Client Error",
				],
			},
		);
		frappeRequest.mockImplementation(async ({ url }) => {
			if (url.endsWith("fetch_remote_card")) throw failure;
			return [REMOTE];
		});

		createApp(A2ARemoteAgents, { onError: (message) => errors.push(message) }).mount({});
		await flush();
		await globalThis.__buttons["Fetch card"]();

		expect(errors.at(-1)).toBe(
			"Could not fetch an agent card from https://ba.example: 403 Client Error",
		);
		expect(texts.join(" ")).not.toContain("Card fetched for BA Agent.");
	});

	it("says so when a card is fetched, and shows when", async () => {
		const fetched = {
			...REMOTE,
			card_name: "Dev Agent",
			card_fetched_at: "2026-11-17 12:23:48.607383",
		};
		frappeRequest.mockImplementation(async ({ url }) =>
			url.endsWith("fetch_remote_card") ? { name: "Dev Agent" } : [fetched],
		);

		createApp(A2ARemoteAgents).mount({});
		await flush();
		expect(texts.join(" ")).not.toContain("Card fetched for BA Agent.");

		await globalThis.__buttons["Fetch card"]();
		await flush();

		expect(texts.join(" ")).toContain("Card fetched for BA Agent.");
		expect(texts.join(" ")).toContain("fetched 2026-11-17 12:23");
	});
});
