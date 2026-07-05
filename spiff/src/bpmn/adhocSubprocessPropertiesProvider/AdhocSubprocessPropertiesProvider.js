import { AdhocSubprocessProps } from "./AdhocSubprocessProps";
import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

/**
 * Properties panel provider for Ad-hoc Subprocesses (WI-001349).
 *
 * bpmn-js 18's stock Change element menu already offers "Ad-hoc sub-process"
 * for expanded subprocesses (and the reverse conversion back to a plain
 * Sub-process, which drops completionCondition/cancelRemainingInstances since
 * both are metamodel-scoped to bpmn:AdHocSubProcess). This provider adds the
 * missing editing surface: a group with the Completion Condition and Cancel
 * Remaining Instances fields.
 */
export default class AdhocSubprocessPropertiesProvider {
	constructor(propertiesPanel, translate) {
		propertiesPanel.registerProvider(LOW_PRIORITY, this);
		this.translate = translate;
	}

	getGroups(element) {
		return (groups) => {
			if (!is(element, "bpmn:AdHocSubProcess")) {
				return groups;
			}

			groups.push({
				id: "AdhocSubprocessConfiguration",
				label: this.translate("Ad-hoc Subprocess"),
				entries: AdhocSubprocessProps({ element }),
			});

			return groups;
		};
	}
}

AdhocSubprocessPropertiesProvider.$inject = ["propertiesPanel", "translate"];
