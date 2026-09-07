// Copyright (c) 2026, one-fm and contributors
// one-ai bundle entry (WI-001678). Built as a self-contained IIFE (Vue
// included) so a page outside the SPA can mount the shared chat surface.
// Two hosts share it, which is why it stays one artifact: the standalone
// /one-ai website page (www/one_ai) and, inside Desk, the Chat button's
// dialog. Exposes:
//   window.oneAI.mount(el)              — the full one-ai page app
//   window.oneAI.openAgentChat(opts)    — the panel in a dialog for one agent
//                                          (the WI-001996 Chat button target)
import { createApp, h } from "vue";
import AgentChatPanel from "./components/chat/AgentChatPanel.vue";
import OneAiApp from "./components/chat/OneAiApp.vue";
import { cardRegistry } from "./components/chat/cards/registry";

// Desk provides the CSRF token on the frappe global; frappe-ui's request
// helper reads window.csrf_token, which only the SPA's index.html sets.
// Without this bridge every POST from this bundle (get_agent_surface,
// conversation_history, …) fails CSRF on Desk while the SSE GET stream
// works — so chat answered but the agent's surface config never loaded
// (diagnosed live 2026-08-10: the Chat dialog fell back to the raw
// agent_id label and the conversation layout, whatever the configuration
// said).
if (!window.csrf_token && window.frappe && window.frappe.csrf_token) {
	window.csrf_token = window.frappe.csrf_token;
}

function mount(el) {
	const app = createApp(OneAiApp);
	app.mount(el);
	return app;
}

function openAgentChat({ agent_id: agentId, conversation = "" } = {}) {
	if (!agentId) return;
	const scrim = document.createElement("div");
	scrim.className = "oneai-dialog-scrim";
	const box = document.createElement("div");
	box.className = "oneai-dialog-box";
	scrim.appendChild(box);
	document.body.appendChild(scrim);

	const app = createApp({
		render() {
			return h(AgentChatPanel, {
				agentId,
				conversation,
				variant: "modal",
				cards: cardRegistry,
				allowUploads: true,
				// Pure chat host: no editor, canvas, builder, or form behind
				// this dialog — artifact cards render as previews (decision 3,
				// chat-surface-layout scope: hide Apply, keep Dismiss).
				applyTargets: [],
			});
		},
	});
	app.mount(box);

	const close = () => {
		app.unmount(); // end_chat_conversation fires in the panel's unmount hook
		scrim.remove();
	};
	scrim.addEventListener("click", (e) => { if (e.target === scrim) close(); });
	return { close };
}

const styles = `
.oneai-dialog-scrim { position: fixed; inset: 0; background: rgba(23,23,23,.45); z-index: 1050;
	display: flex; align-items: flex-start; justify-content: center; padding-top: 48px; }
.oneai-dialog-box { width: min(960px, 92vw); background: var(--card-bg, #fff); border-radius: 12px;
	overflow: hidden; box-shadow: 0 12px 32px rgba(0,0,0,.18); }
`;
const styleEl = document.createElement("style");
styleEl.textContent = styles;
document.head.appendChild(styleEl);

window.oneAI = Object.assign(window.oneAI || {}, { mount, openAgentChat });
export { mount, openAgentChat };
