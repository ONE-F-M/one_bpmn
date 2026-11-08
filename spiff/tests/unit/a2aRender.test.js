import { describe, expect, it, vi } from "vitest";

vi.mock("frappe-ui", async () => {
	const { h } = await import("vue");
	return {
		frappeRequest: vi.fn().mockResolvedValue({}),
		Badge: {
			render() {
				return h("span", { class: "badge" }, this.$slots.default?.());
			},
		},
		Button: {
			props: ["disabled"],
			render() {
				return h("button", { disabled: this.disabled }, this.$slots.default?.());
			},
		},
		ErrorMessage: {
			props: ["message"],
			render() {
				return h("p", this.message);
			},
		},
		FormControl: {
			props: ["label", "modelValue"],
			render() {
				return h("div", { class: "form-control" }, this.label);
			},
		},
		Dialog: {
			props: ["modelValue", "options"],
			render() {
				if (!this.modelValue) return h("div");
				return h("div", { class: "dialog" }, [
					h("h2", this.options?.title),
					this.$slots["body-content"]?.(),
					this.$slots.actions?.(),
				]);
			},
		},
	};
});

const { createSSRApp, h } = await import("vue");
const { renderToString } = await import("vue/server-renderer");

const parts = import.meta.glob("../../src/components/A2A/*/*.vue", { eager: true });
const part = (name) => parts[`../../src/components/A2A/${name}/${name}.vue`].default;

async function render(component, props = {}) {
	const app = createSSRApp({ render: () => h(component, props) });
	app.component("RouterLink", {
		render() {
			return h("a", this.$slots.default?.());
		},
	});
	return renderToString(app);
}

const OPTIONS = { statuses: [], doctypes: [], workers: [], task_agents: [] };

describe("A2APager", () => {
	it("shows the window and disables Previous on the first page", async () => {
		const html = await render(part("A2APager"), {
			start: 0,
			count: 10,
			total: 293,
			pageLength: 10,
		});
		expect(html).toContain("Showing 1 to");
		expect(html).toContain("10 of 293");
		expect(html).toMatch(/<button[^>]*disabled[^>]*>Previous/);
		expect(html).not.toMatch(/<button[^>]*disabled[^>]*>\s*Next/);
	});

	it("disables Next on the last page", async () => {
		const html = await render(part("A2APager"), {
			start: 290,
			count: 3,
			total: 293,
			pageLength: 10,
		});
		expect(html).toMatch(/<button[^>]*disabled[^>]*>\s*Next/);
	});

	it("shows zero for an empty list", async () => {
		const html = await render(part("A2APager"), {
			start: 0,
			count: 0,
			total: 0,
			pageLength: 20,
		});
		expect(html).toContain("Showing 0 to");
	});
});

describe("A2ADelegationActions", () => {
	const actionsFor = (status) =>
		render(part("A2ADelegationActions"), { row: { name: "AD-1", status } });

	it("offers a hand back, and no cancel, for work that failed", async () => {
		const html = await actionsFor("Failed");
		expect(html).toContain("Hand back to the agent");
		expect(html).not.toContain("Cancel delegation");
	});

	it("offers a cancel, and no hand back, for work still running", async () => {
		const html = await actionsFor("In Progress");
		expect(html).toContain("Cancel delegation");
		expect(html).not.toContain("Hand back to the agent");
	});

	it("offers neither for work that finished", async () => {
		const html = await actionsFor("Completed");
		expect(html).not.toContain("Cancel delegation");
		expect(html).not.toContain("Hand back to the agent");
	});

	it("offers both for work waiting on review", async () => {
		const html = await actionsFor("Needs Review");
		expect(html).toContain("Cancel delegation");
		expect(html).toContain("Hand back to the agent");
	});
});

describe("A2ADelegationModal", () => {
	const row = {
		name: "AD-1",
		status: "Failed",
		delegating_agent: "Orchestrator",
		worker_agent: "Worker",
		stopped_reason: "max_recursion_depth",
		limit_value: 3,
		reached_value: 3,
		reference_doctype: "Sales Order",
		reference_name: "SO-1",
		a2a_task: "A2A-9",
	};

	it("renders nothing while the dialog is closed", async () => {
		const html = await render(part("A2ADelegationModal"), { modelValue: false, row });
		expect(html).not.toContain("Delegation");
	});

	it("shows loading before the detail arrives", async () => {
		const html = await render(part("A2ADelegationModal"), {
			modelValue: true,
			row,
			loading: true,
		});
		expect(html).toContain("Loading…");
		expect(html).not.toContain("Orchestrator");
	});

	it("names the limit that stopped it in plain words, and links the work", async () => {
		const html = await render(part("A2ADelegationModal"), { modelValue: true, row });
		expect(html).toContain("Stopped at a limit");
		expect(html).toContain("nesting depth");
		expect(html).toContain('href="/app/sales-order/SO-1"');
		expect(html).toContain('href="/app/a2a-task/A2A-9"');
	});

	it("says who cancelled it instead of showing a limit", async () => {
		const html = await render(part("A2ADelegationModal"), {
			modelValue: true,
			row: { ...row, status: "Cancelled", cancelled_by: "boss@example.com" },
		});
		expect(html).toContain("Cancelled by a person");
		expect(html).not.toContain("Stopped at a limit");
	});

	it("answers 'no answer recorded' when nothing came back", async () => {
		const html = await render(part("A2ADelegationModal"), { modelValue: true, row });
		expect(html).toContain("no answer recorded");
	});
});

describe("A2AClarificationModal", () => {
	const row = {
		name: "AC-2",
		status: "Awaiting Answer",
		agent_configuration: "Bug Agent",
		owner_asked: "boss@example.com",
		question: "Which one?",
		reference_doctype: "User",
		reference_name: "Administrator",
	};
	const thread = [
		{ name: "AC-1", round: 1, status: "Answered", question: "First?", answer: "Yes" },
		{ name: "AC-2", round: 2, status: "Awaiting Answer", question: "Which one?" },
	];

	it("says the agent is waiting and will not guess", async () => {
		const html = await render(part("A2AClarificationModal"), { modelValue: true, row });
		expect(html).toContain("Still waiting");
		expect(html).toContain("Which one?");
		expect(html).toContain('href="/app/user/Administrator"');
	});

	it("shows the whole exchange only when there is more than one round", async () => {
		const single = await render(part("A2AClarificationModal"), {
			modelValue: true,
			row,
			thread: [thread[1]],
		});
		expect(single).not.toContain("The whole exchange");
		const many = await render(part("A2AClarificationModal"), {
			modelValue: true,
			row,
			thread,
		});
		expect(many).toContain("The whole exchange");
		expect(many).toContain("Round 1");
	});
});

describe("the tab parts", () => {
	it("renders an empty remote agents list with its own scroll container", async () => {
		const html = await render(part("A2ARemoteAgents"));
		expect(html).toContain("No remote agents registered yet.");
		expect(html).toContain("overflow-x-auto");
	});

	it("renders an empty clients list", async () => {
		const html = await render(part("A2AClients"), { ourAgents: [] });
		expect(html).toContain("No clients registered yet.");
		expect(html).toContain("overflow-x-auto");
	});

	it("renders the tasks list with narrow-screen filters and pager", async () => {
		const html = await render(part("A2ATasks"), { filterOptions: OPTIONS });
		expect(html).toContain("No tasks yet.");
		expect(html).toContain("Showing 0 to");
	});

	it("renders the delegations list", async () => {
		const html = await render(part("A2ADelegations"), { filterOptions: OPTIONS });
		expect(html).toContain("No delegations yet.");
		expect(html).toContain("overflow-x-auto");
	});

	it("renders the clarifications list", async () => {
		const html = await render(part("A2AClarifications"));
		expect(html).toContain("No agent has needed to ask anything yet.");
		expect(html).toContain("overflow-x-auto");
	});
});
