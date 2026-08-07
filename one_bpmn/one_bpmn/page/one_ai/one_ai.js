// Copyright (c) 2026, one-fm and contributors
// /app/one-ai (WI-001678) — the Lumina successor, hosted in one_bpmn.
// The page is a mount point: the self-contained one-ai bundle (Vue included)
// carries the shared AgentChatPanel, the history sidebar and the
// registry-driven agent picker. The legacy /app/lumina page in onefm_mcp is
// SUPERSEDED by this page, not deleted here — its removal rides the
// onefm_mcp retirement (WI-001669 / WI-001964).
frappe.pages["one-ai"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("ONE AI"),
		single_column: true,
	});

	const host = document.createElement("div");
	host.className = "one-ai-host";
	page.body.get(0).appendChild(host);

	frappe.require(
		["/assets/one_bpmn/one_ai/one-ai.css", "/assets/one_bpmn/one_ai/one-ai.iife.js"],
		() => {
			if (window.oneAI && typeof window.oneAI.mount === "function") {
				window.oneAI.mount(host);
			} else {
				host.innerHTML = `<div class="text-muted" style="padding:2rem">${__(
					"The ONE AI bundle is missing — run `npm run build:oneai` in one_bpmn/spiff."
				)}</div>`;
			}
		}
	);
};
