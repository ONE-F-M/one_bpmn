/**
 * Shape attribute access for the AI Agent Task and AI Task Selector panels.
 *
 * A shape that links an AI Agent Configuration takes its prompt, model and
 * params from that record at run time (agent_config_resolver), so an edit that
 * only reached the diagram would look saved and change nothing. Writes go back
 * to the configuration too, the same way the task dialog's Save does.
 */
import { TextAreaEntry } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { Component, h } from "preact";

import { serverMessage } from "@/utils/serverMessage";
import { frappePost } from "./frappeResource";
import "./bpmn-panel.css";

// The only panel field the linked configuration also stores. Everything else
// here is diagram-only, or read-only once a configuration is linked.
const CONFIG_BACKED = new Set(["aiSystemPrompt"]);
const SYNC_DELAY_MS = 1200;
const pending = new Map();

export function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

export function setAttr(modeling, element, bo, attr, value, onResult) {
	modeling.updateModdleProperties(element, bo, {
		[`spiffworkflow:${attr}`]: value || undefined,
	});
	if (CONFIG_BACKED.has(attr)) {
		syncToConfig(getAttr(bo, "aiAgentConfig"), attr, value, onResult);
	}
}

// One write per typing burst. The endpoint is a no-op when nothing actually
// changed, so it only re-provisions a Live agent on a real edit.
function syncToConfig(config, attr, value, onResult) {
	if (!config) return;
	const key = `${config}::${attr}`;
	clearTimeout(pending.get(key));
	pending.set(
		key,
		setTimeout(() => {
			pending.delete(key);
			frappePost(
				"/api/method/one_bpmn.agents.agent_config_resolver.update_agent_config_from_shape",
				{ config_name: config, fields: JSON.stringify({ [attr]: value || "" }) }
			)
				.then(() => onResult && onResult(null))
				.catch((e) => onResult && onResult(serverMessage(e)));
		}, SYNC_DELAY_MS)
	);
}

/**
 * The System Prompt box, showing the linked configuration's prompt rather than
 * the shape's copy of it — that copy is what a stale diagram carries, and the
 * configuration is what dispatch actually sends. Falls back to the shape when
 * the agent has no prompt of its own, exactly as dispatch does.
 */
const LIVE_PROMPT = new Map(); // config name -> prompt, or null when the config has none
const LIVE_LOADING = new Set();
const TYPED = new WeakSet(); // shapes whose box the designer has typed into this session
const SYNC_ERROR = new WeakMap();

async function loadLivePrompt(config, bo) {
	try {
		const fields = await frappePost(
			"/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
			{ config_name: config }
		);
		LIVE_PROMPT.set(config, fields?.aiSystemPrompt || null);
	} catch (err) {
		LIVE_PROMPT.set(config, null);
		SYNC_ERROR.set(bo, serverMessage(err));
	}
}

export function LinkedPromptEntry({ bo, modeling, element, id, ...entry }) {
	const eventBus = useService("eventBus");
	const config = getAttr(bo, "aiAgentConfig");
	// Re-render through the panel's own Preact; a class setState here stalls the panel's updates.
	const refresh = () => eventBus.fire("elements.changed", { elements: [element] });

	if (config && !LIVE_PROMPT.has(config) && !LIVE_LOADING.has(config)) {
		LIVE_LOADING.add(config);
		loadLivePrompt(config, bo).then(() => {
			LIVE_LOADING.delete(config);
			refresh();
		});
	}

	return h(TextAreaEntry, {
		...entry,
		element,
		id,
		getValue: () => (!TYPED.has(bo) && LIVE_PROMPT.get(config)) || getAttr(bo, "aiSystemPrompt"),
		// A rejected write or an unreadable configuration is said on the field, since the agent is what runs.
		validate: () => SYNC_ERROR.get(bo) || null,
		setValue: (value) => {
			// Once the designer types, the box shows the shape attribute their keystrokes write to.
			TYPED.add(bo);
			setAttr(modeling, element, bo, "aiSystemPrompt", value, (error) => {
				SYNC_ERROR.set(bo, error);
				refresh();
			});
		},
	});
}

const DRIFT_ATTRS = [
	"aiSystemPrompt",
	"aiModel",
	"aiTemperature",
	"aiMaxTokens",
	"aiTimeout",
	"aiMaxRetries",
	"aiMaxToolCalls",
	"aiTopP",
];
const PROMPT_PREVIEW_CHARS = 160;

/**
 * One "differs from configuration" marker per field whose shape copy disagrees
 * with the linked configuration, showing the value that runs.
 */
export class DriftMarkers extends Component {
	state = { drift: [] };

	componentDidMount() {
		const { bo } = this.props;
		const config = getAttr(bo, "aiAgentConfig");
		if (!config) return;
		const shape = Object.fromEntries(DRIFT_ATTRS.map((attr) => [attr, getAttr(bo, attr)]));
		frappePost("/api/method/one_bpmn.agents.agent_config_resolver.get_shape_drift", {
			config_name: config,
			shape: JSON.stringify(shape),
		})
			.then((drift) => this.setState({ drift: drift || [] }))
			.catch((e) => this.setState({ drift: [{ field: "error", label: serverMessage(e), live: "" }] }));
	}

	render({ id, translate }) {
		const { drift } = this.state;
		if (!drift.length) return null;
		return h(
			"div",
			{ class: "bio-properties-panel-entry", "data-entry-id": id },
			h(
				"ul",
				{ class: "bpmn-drift-list" },
				drift.map((d) =>
					h("li", { key: d.field, class: "bpmn-drift-item" }, [
						h("strong", null, `${d.label}: ${translate("differs from configuration")}`),
						h("span", { class: "bpmn-drift-live" }, `${translate("Runs")}: ${livePreview(d)}`),
					])
				)
			)
		);
	}
}

function livePreview(d) {
	const text = String(d.live ?? "");
	return text.length > PROMPT_PREVIEW_CHARS ? `${text.slice(0, PROMPT_PREVIEW_CHARS)}...` : text;
}
