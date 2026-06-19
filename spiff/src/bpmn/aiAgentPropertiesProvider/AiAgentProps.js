import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

// Human-readable labels for the executor backend stored in spiffworkflow:aiBackend.
const BACKEND_LABELS = {
	direct_api: "Direct API (OpenAI-compatible)",
	antigravity: "Google Antigravity SDK",
};

// A task counts as "configured" once an AI Provider is selected AND the core
// task instruction (the user prompt / context) has been entered.
function isConfigured(bo) {
	return Boolean(getAttr(bo, "aiProvider")) && Boolean(getAttr(bo, "aiUserPrompt"));
}

const LAUNCH_BUTTON_STYLE = [
	"padding: 6px 14px",
	"background: #6366f1",
	"color: #fff",
	"border: none",
	"border-radius: 4px",
	"cursor: pointer",
	"font-size: 0.82rem",
	"font-weight: 500",
].join(";");

// ---------------------------------------------------------------------------
// Entry list — chooses the configured (summary + edit) or unconfigured
// (configure button) view.
// ---------------------------------------------------------------------------
export function AiAgentProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);

	if (!isConfigured(bo)) {
		return [
			{ id: "ai-agent-configure", element, component: ConfigureButtonComponent },
		];
	}

	return [
		{ id: "ai-agent-summary", element, component: SummaryComponent },
		{ id: "ai-agent-edit",    element, component: EditButtonComponent },
	];
}

// ---------------------------------------------------------------------------
// Not-configured view — prompt + Configure button
// ---------------------------------------------------------------------------
function ConfigureButtonComponent(props) {
	const { element } = props;
	const translate = useService("translate");
	const eventBus  = useService("eventBus");

	return h("div", { style: "padding: 6px 0;" }, [
		h("div", {
			style: "font-size: 0.8rem; color: #6b7280; margin-bottom: 10px; line-height: 1.4;",
		}, translate("This AI Agent Task is not configured yet. Set the provider and prompts to get started.")),
		h("button", {
			style: LAUNCH_BUTTON_STYLE,
			onClick: () => eventBus.fire("launch-ai-agent-editor", { element }),
		}, translate("Configure AI Task")),
	]);
}

// ---------------------------------------------------------------------------
// Configured view — key summary fields (read-only)
// ---------------------------------------------------------------------------
function SummaryComponent(props) {
	const { element } = props;
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const backendRaw    = getAttr(bo, "aiBackend");
	const responseFormat = getAttr(bo, "aiResponseFormat") || "text";

	const rows = [
		[translate("Backend"),         BACKEND_LABELS[backendRaw] || backendRaw || "—"],
		[translate("AI Provider"),     getAttr(bo, "aiProvider") || "—"],
		[translate("Model"),           getAttr(bo, "aiModel") || translate("(provider default)")],
		[translate("Output Variable"), getAttr(bo, "aiOutputVariable") || "—"],
		[translate("Response Format"), responseFormat === "json" ? "JSON" : "Text"],
	];

	return h("div", {
		style: "padding: 4px 0; display: flex; flex-direction: column; gap: 8px;",
	}, rows.map(([label, value]) =>
		h("div", { style: "display: flex; flex-direction: column; gap: 2px;" }, [
			h("span", {
				style: "font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: #9ca3af;",
			}, label),
			h("span", {
				style: "font-size: 0.85rem; color: #111827; word-break: break-word;",
			}, value),
		])
	));
}

// ---------------------------------------------------------------------------
// Configured view — Edit button
// ---------------------------------------------------------------------------
function EditButtonComponent(props) {
	const { element } = props;
	const translate = useService("translate");
	const eventBus  = useService("eventBus");

	return h("div", { style: "padding: 8px 0 4px;" },
		h("button", {
			style: LAUNCH_BUTTON_STYLE,
			onClick: () => eventBus.fire("launch-ai-agent-editor", { element }),
		}, translate("Edit AI Task Configuration"))
	);
}
