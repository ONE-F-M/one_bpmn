import { beforeEach, describe, expect, it, vi } from "vitest";

// The button text is what the tests read, so each stub renders only its default slot.
vi.mock("frappe-ui", async () => {
	const { h } = await import("vue");
	const slotOnly = {
		setup:
			(_, { slots }) =>
			() =>
				h("span", slots.default?.()),
	};
	return {
		Button: slotOnly,
		Dialog: slotOnly,
		Dropdown: slotOnly,
		ErrorMessage: slotOnly,
		FormControl: slotOnly,
	};
});
vi.mock("@/composables/useCurrentUser", async () => {
	const { ref } = await import("vue");
	return { useCurrentUser: () => ({ currentRoles: ref(["System Manager"]) }) };
});
vi.mock("@/composables/useInstanceControl", () => ({
	useInstanceControl: () => ({ busy: globalThis.__instanceControlBusy, runControl: vi.fn() }),
}));

const { createSSRApp, ref } = await import("vue");
const { renderToString } = await import("vue/server-renderer");
const InstanceControls = (
	await import("../../src/components/Instances/InstanceControls/InstanceControls.vue")
).default;

async function render(status) {
	return renderToString(createSSRApp(InstanceControls, { details: { name: "inst1", status } }));
}

describe("the retry button", () => {
	beforeEach(() => {
		globalThis.__instanceControlBusy = ref("");
	});

	it("says Retry failed step on an Errored instance", async () => {
		expect(await render("Errored")).toContain("Retry failed step");
	});

	it("says Retrying while the retry runs", async () => {
		globalThis.__instanceControlBusy.value = "retry_failed_step";
		const html = await render("Errored");
		expect(html).toContain("Retrying…");
		expect(html).not.toContain("Retry failed step");
	});

	it("keeps its own label while another action runs", async () => {
		globalThis.__instanceControlBusy.value = "resume_instance";
		expect(await render("Errored")).toContain("Retry failed step");
	});
});
