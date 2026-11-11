import { is } from "bpmn-js/lib/util/ModelUtil";

const LOW_PRIORITY = 500;

const matches = (element, type) => [].concat(type).some((t) => is(element, t));

/**
 * Builds the class the properties panel registers: it adds one group to elements of one BPMN
 * type (or of any type in an array). With `edit` it changes the existing groups instead, and
 * `priority`, `inject` (extra services, by name) and `setup` (builds per-instance state) apply.
 */
export function makeProvider(
	type,
	groupId,
	label,
	propsFn,
	{
		prepend = false,
		when = () => true,
		tooltip,
		priority = LOW_PRIORITY,
		inject = [],
		setup,
		edit,
	} = {},
) {
	class PropertiesProvider {
		constructor(propertiesPanel, translate, ...services) {
			propertiesPanel.registerProvider(priority, this);
			this.translate = translate;
			this.state = setup?.({
				translate,
				...Object.fromEntries(inject.map((name, index) => [name, services[index]])),
			});
		}

		getGroups(element) {
			return (groups) => {
				if (!matches(element, type) || !when(element)) {
					return groups;
				}

				if (edit) {
					edit({ groups, element, state: this.state });
					return groups;
				}

				const group = {
					id: groupId,
					label: this.translate(label),
					entries: propsFn({ element }),
				};
				if (tooltip) {
					group.tooltip = this.translate(tooltip);
				}
				if (prepend) {
					groups.unshift(group);
				} else {
					groups.push(group);
				}

				return groups;
			};
		}
	}

	PropertiesProvider.$inject = ["propertiesPanel", "translate", ...inject];

	return PropertiesProvider;
}
