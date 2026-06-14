import { BusinessRuleTaskProps } from "./BusinessRuleTaskProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

/**
 * Registers a custom properties panel group for bpmn:BusinessRuleTask elements.
 *
 * Shows a "Business Rule Properties" group with:
 *   - Decision Table picker (Frappe-stored DMN autocomplete)
 *   - Launch Editor button (opens DMN editor dialog)
 *
 * This replaces the default SpiffWorkflow DMN properties group with a
 * Frappe-native implementation that searches Workflow Decision Table
 * child rows by both decision_id and decision_name.
 */
export default function BusinessRuleTaskPropertiesProvider(propertiesPanel, translate) {
	this.getGroups = function (element) {
		return function (groups) {
			if (!is(element, "bpmn:BusinessRuleTask")) return groups;

			groups.push({
				id: "businessRuleConfiguration",
				label: translate("Business Rule Properties"),
				entries: BusinessRuleTaskProps({ element }),
				tooltip: translate(
					"Link a Frappe-stored DMN decision table to execute when this Business Rule Task runs."
				),
			});

			return groups;
		};
	};

	propertiesPanel.registerProvider(LOW_PRIORITY, this);
}

BusinessRuleTaskPropertiesProvider.$inject = ["propertiesPanel", "translate"];
