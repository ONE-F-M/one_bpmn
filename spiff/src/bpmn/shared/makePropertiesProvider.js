import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

/** Builds the class the properties panel registers: it adds one group to elements of one BPMN type. */
export function makeProvider(
	type,
	groupId,
	label,
	propsFn,
	{ prepend = false, when = () => true } = {},
) {
	class PropertiesProvider {
		constructor(propertiesPanel, translate) {
			propertiesPanel.registerProvider(LOW_PRIORITY, this);
			this.translate = translate;
		}

		getGroups(element) {
			return (groups) => {
				if (!is(element, type) || !when(element)) {
					return groups;
				}

				const group = {
					id: groupId,
					label: this.translate(label),
					entries: propsFn({ element }),
				};
				if (prepend) {
					groups.unshift(group);
				} else {
					groups.push(group);
				}

				return groups;
			};
		}
	}

	PropertiesProvider.$inject = ["propertiesPanel", "translate"];

	return PropertiesProvider;
}
