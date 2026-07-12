import { useService } from "bpmn-js-properties-panel";
// The properties panel renders with the preact copy VENDORED inside
// @bpmn-io/properties-panel (its dist imports it by relative path, so
// vite's alias/dedupe cannot unify it with the root "preact"). Hooks are
// bound to the preact instance doing the render — importing them from
// the root copy makes useState crash with "Cannot read properties of
// undefined (reading '__H')" and freezes the panel. Import h and the
// hooks from the panel's own copy instead.
import { h } from "@bpmn-io/properties-panel/preact";
import { useEffect, useState } from "@bpmn-io/properties-panel/preact/hooks";
import { frappeGet, frappePost } from "../shared/frappeResource";
import "../shared/bpmn-panel.css";

/**
 * "Registry Tools" section for an AI Task Selector (WI-001357).
 *
 * Lists enabled AI Agent Tool records with their applicability to the
 * current process. Checking/unchecking adds/removes this process from the
 * tool's applicable_processes (server-side permission checked). Global
 * tools (empty applicable_processes) are always available and shown
 * without a checkbox — scoping a global tool is an explicit decision made
 * on the tool record, not a checkbox side effect.
 */
export function AiToolRegistryProps(props) {
	const { element, processModel } = props;
	return [
		{
			id: "ai-registry-tools",
			element,
			component: (entryProps) => h(RegistryToolList, { ...entryProps, processModel }),
		},
	];
}

function RegistryToolList(props) {
	const { id, processModel } = props;
	const translate = useService("translate");
	const [tools, setTools] = useState(null);
	const [error, setError] = useState("");

	const load = () => {
		frappeGet("/api/method/one_bpmn.api.tool_registry_api.list_registry_tools", {
			process_model: processModel || "",
		})
			.then((rows) => setTools(rows || []))
			.catch(() => setError(translate("Could not load registry tools.")));
	};

	useEffect(load, [processModel]);

	const toggle = (tool, applicable) => {
		frappePost("/api/method/one_bpmn.api.tool_registry_api.set_tool_process_applicability", {
			tool: tool.name,
			process_model: processModel || "",
			applicable: applicable ? 1 : 0,
		})
			.then(load)
			.catch((exc) => {
				const msg = exc?.message || translate("Update failed — check your permissions.");
				setError(msg);
				setTimeout(() => setError(""), 4000);
			});
	};

	let body;
	if (error) {
		body = h("div", { class: "bio-properties-panel-description" }, error);
	} else if (tools === null) {
		body = h("div", { class: "bio-properties-panel-description" }, translate("Loading…"));
	} else if (!tools.length) {
		body = h(
			"div",
			{ class: "bio-properties-panel-description" },
			translate("No active AI Agent Tools. Create them in the AI Agent Tool list.")
		);
	} else {
		body = h(
			"ul",
			// NOT .bio-properties-panel-list — the panel hides that class
			// (display:none) unless its own list-group toggles .open on it.
			{ class: "bpmn-registry-tools" },
			tools.map((tool) =>
				h("li", { key: tool.name, class: "bpmn-registry-tool-item" }, [
					tool.is_global
						? h("span", { title: translate("Global — available to every process") }, "🌐 ")
						: h("input", {
								type: "checkbox",
								checked: !!tool.applies_here,
								onChange: (event) => toggle(tool, event.target.checked),
							}),
					h("strong", null, ` ${tool.tool_name} `),
					h("span", { class: "bio-properties-panel-description" }, tool.description || ""),
				])
			)
		);
	}

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", null, [
			h("label", { class: "bio-properties-panel-label" }, translate("Registry Tools")),
			body,
		])
	);
}
