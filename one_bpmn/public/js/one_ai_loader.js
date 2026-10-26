// Copyright (c) 2026, one-fm and contributors
// Lazy loader for the one-ai bundle (WI-001678). Desk-wide but tiny: defines
// window.oneAI.openAgentChat so surfaces like the AI Agent Configuration
// form's Chat button (WI-001996) can open the shared panel on demand; the
// heavy bundle loads only on first use.
(function () {
	window.oneAI = window.oneAI || {};
	if (window.oneAI.openAgentChat) return;
	window.oneAI.openAgentChat = function (opts) {
		// Versioned exactly as the standalone page versions it. Without this the
		// desk requests the bundle by a bare path, the 12h Cache-Control on
		// /assets applies, and a browser that has ever opened the chat keeps
		// running the old build — the failure mode the page's own
		// _asset_version() docstring was written for.
		const v = (frappe.boot && frappe.boot.one_ai_asset_version) || "";
		const q = v ? "?v=" + encodeURIComponent(v) : "";
		frappe.require(
			["/assets/one_bpmn/one_ai/one-ai.css" + q, "/assets/one_bpmn/one_ai/one-ai.iife.js" + q],
			() => {
				// the bundle replaces this stub with the real implementation
				if (window.oneAI.openAgentChat && !window.oneAI.openAgentChat.__stub) {
					window.oneAI.openAgentChat(opts);
				}
			}
		);
	};
	window.oneAI.openAgentChat.__stub = true;
})();
