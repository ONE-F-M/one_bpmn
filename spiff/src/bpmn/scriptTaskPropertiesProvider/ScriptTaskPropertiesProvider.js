import { ScriptTaskProps } from "./ScriptTaskProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

/**
 * Registers a custom properties panel group for bpmn:ScriptTask elements.
 *
 * Shows a "Script Configuration" group with:
 *   - Server Script picker (Frappe Server Script autocomplete)
 *
 * This integrates with the FrappeScriptEngine on the backend which
 * executes the named Server Script with full workflow context when
 * the Script Task runs.
 */
export default function ScriptTaskPropertiesProvider(propertiesPanel, translate) {
	this.getGroups = function (element) {
		return function (groups) {
			if (!is(element, "bpmn:ScriptTask")) return groups;

			groups.push({
				id: "scriptConfiguration",
				label: translate("Script Configuration"),
				entries: ScriptTaskProps({ element }),
				tooltip: translate(
					"Link a Frappe Server Script to execute when this task runs. " +
					"The script has access to the full workflow context."
				),
			});

			return groups;
		};
	};

	propertiesPanel.registerProvider(LOW_PRIORITY, this);
}

ScriptTaskPropertiesProvider.$inject = ["propertiesPanel", "translate"];
