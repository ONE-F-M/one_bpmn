// Copyright (c) 2026, one-fm and contributors
// one-ai desk bundle entry (WI-001678). Built as a self-contained IIFE (Vue
// included) so a Frappe Desk page can mount the shared chat surface without
// the SPA. Exposes:
//   window.oneAI.mount(el)              — the full one-ai page app
//   window.oneAI.openAgentChat(opts)    — the panel in a dialog for one agent
//                                          (the WI-001996 Chat button target)
import { createApp, h } from "vue";
import AgentChatPanel from "./components/chat/AgentChatPanel.vue";
import OneAiApp from "./components/chat/OneAiApp.vue";
import { cardRegistry } from "./components/chat/cards/registry";

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
.oneai-dialog-box { width: min(560px, 92vw); background: var(--card-bg, #fff); border-radius: 12px;
	overflow: hidden; box-shadow: 0 12px 32px rgba(0,0,0,.18); }
`;
const styleEl = document.createElement("style");
styleEl.textContent = styles;
document.head.appendChild(styleEl);

window.oneAI = Object.assign(window.oneAI || {}, { mount, openAgentChat });
export { mount, openAgentChat };
