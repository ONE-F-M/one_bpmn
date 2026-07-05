import { AiToolRegistryProps } from "./AiToolRegistryProps";
import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 400;

/**
 * Adds a "Registry Tools" group to the properties panel for Ad-hoc
 * Subprocesses tagged with spiffworkflow:serviceType="ai_task_selector"
 * (WI-001357). Self-contained: reads the serviceType attribute directly so
 * it composes with, but does not depend on, the selector configuration
 * group (WI-001351).
 */
export default class AiToolRegistryPropertiesProvider {
	constructor(propertiesPanel, translate, canvas) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
		this.canvas = canvas;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:AdHocSubProcess")) {
				return groups;
			}
			const bo = getBusinessObject(element);
			if ((bo.get("spiffworkflow:serviceType") ?? "") !== "ai_task_selector") {
				return groups;
			}

			// The BPMN Process Model name is exposed on the page context by
			// the editor shell (set when a model is opened).
			const processModel =
				window.__ONE_BPMN_CURRENT_MODEL__ ||
				new URLSearchParams(window.location.search).get("model") ||
				"";

			groups.push({
				id: "AiToolRegistry",
				label: this.translate("Registry Tools"),
				entries: AiToolRegistryProps({ element, processModel }),
			});

			return groups;
		};
	}
}

AiToolRegistryPropertiesProvider.$inject = ["propertiesPanel", "translate", "canvas"];
