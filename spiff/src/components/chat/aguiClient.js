// Copyright (c) 2026, one-fm and contributors
// AG-UI SSE client for the shared AgentChatPanel (WI-001672).
//
// One turn = one EventSource GET against the shared endpoint (WI-001670).
// The read loop mirrors the production-proven parsing in onefm_mcp's
// chat_widget.js, reduced to what the panel consumes: every `data:` line is
// one JSON event; RUN_FINISHED / RUN_ERROR terminate the turn; comment
// lines (keep-alives) are transport and never reach the callbacks.

const ENDPOINT = "/api/method/one_bpmn.api.agui.stream_agent_turn";

/**
 * Stream one agent turn.
 *
 * @param {Object} opts
 * @param {string} opts.agentId
 * @param {string} opts.message
 * @param {string} [opts.conversation]  omit on the first turn — the
 *        conversation id arrives on RUN_STARTED as thread_id
 * @param {Object} [opts.context]      host state for this turn
 * @param {(event: Object) => void} opts.onEvent   every parsed event
 * @param {(message: string) => void} opts.onError RUN_ERROR or transport failure
 * @param {() => void} opts.onDone     terminal — stream closed
 * @returns {{ close: () => void }}
 */
export function streamAgentTurn({ agentId, message, conversation, context, onEvent, onError, onDone }) {
	const params = new URLSearchParams({ agent_id: agentId, message });
	if (conversation) params.set("conversation", conversation);
	if (context && Object.keys(context).length) params.set("context", JSON.stringify(context));

	const source = new EventSource(`${ENDPOINT}?${params.toString()}`, { withCredentials: true });
	let finished = false;

	const finish = () => {
		if (finished) return;
		finished = true;
		source.close();
		onDone && onDone();
	};

	source.onmessage = (msg) => {
		if (!msg.data) return;
		let event;
		try {
			event = JSON.parse(msg.data);
		} catch (e) {
			return; // not ours — ignore, never break the transcript
		}
		const type = (event.type || "").toUpperCase();
		if (type === "RUN_ERROR") {
			onError && onError(event.message || "The agent failed to reply.");
			// RUN_FINISHED still follows per contract; wait for it.
			return;
		}
		onEvent && onEvent(event);
		if (type === "RUN_FINISHED") finish();
	};

	source.onerror = () => {
		if (finished) return;
		onError && onError("Connection lost. Please try again.");
		finish();
	};

	return { close: finish };
}
