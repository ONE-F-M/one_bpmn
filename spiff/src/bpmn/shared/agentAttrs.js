/**
 * Shape attribute access for the AI Agent Task and AI Task Selector panels.
 *
 * A shape that links an AI Agent Configuration takes its prompt, model and
 * params from that record at run time (agent_config_resolver), so an edit that
 * only reached the diagram would look saved and change nothing. Writes go back
 * to the configuration too, the same way the task dialog's Save does.
 */
import { useEffect, useState } from "preact/hooks";

import { frappePost } from "./frappeResource";

// The only panel field the linked configuration also stores. Everything else
// here is diagram-only, or read-only once a configuration is linked.
const CONFIG_BACKED = new Set(["aiSystemPrompt"]);
const SYNC_DELAY_MS = 1200;
const pending = new Map();

export function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

export function setAttr(modeling, element, bo, attr, value) {
	modeling.updateModdleProperties(element, bo, {
		[`spiffworkflow:${attr}`]: value || undefined,
	});
	if (CONFIG_BACKED.has(attr)) {
		syncToConfig(getAttr(bo, "aiAgentConfig"), attr, value);
	}
}

// One write per typing burst. The endpoint is a no-op when nothing actually
// changed, so it only re-provisions a Live agent on a real edit.
function syncToConfig(config, attr, value) {
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
			).catch((e) => console.error(`Could not write ${attr} to "${config}"`, e));
		}, SYNC_DELAY_MS)
	);
}

/**
 * The linked configuration's prompt, or null when it has none and the shape's
 * own copy is what dispatch would use. Fetched per mount — the task dialog can
 * change it between two visits to the same shape.
 */
export function useConfigValue(bo, attr) {
	const config = getAttr(bo, "aiAgentConfig");
	const [value, setValue] = useState(null);

	useEffect(() => {
		let live = true;
		if (!config) {
			setValue(null);
			return;
		}
		frappePost(
			"/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
			{ config_name: config }
		)
			.then((fields) => live && setValue(fields?.[attr] || null))
			.catch(() => live && setValue(null));
		return () => {
			live = false;
		};
	}, [config, attr]);

	return value;
}
