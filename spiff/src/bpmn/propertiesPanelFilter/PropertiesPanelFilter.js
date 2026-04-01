import { is } from "bpmn-js/lib/util/ModelUtil";

/**
 * A properties panel provider that runs at the lowest priority to filter out
 * (remove) unwanted property groups from various BPMN element types.
 *
 * Group IDs targeted:
 *   - spiff_pre_post_scripts  → "Pre/Post Scripts"
 *   - user_task_properties    → "Web Form (with Json Schemas)"
 *   - instructions            → "Instructions"
 *   - allow_guest_user        → "Guest options"
 *   - ioProperties            → "Input/Output Management"
 */

const LOWEST_PRIORITY = 100;

/**
 * Map of BPMN element types → set of group IDs to hide.
 */
const HIDDEN_GROUPS = {
	// 1) User Task: hide Pre/Post Scripts, Web Form, Guest Options, I/O Management
	"bpmn:UserTask": new Set([
		"spiff_pre_post_scripts",
		"user_task_properties",
		"allow_guest_user",
		"ioProperties",
	]),

	// 2) Service Task: hide Pre/Post Scripts, Instructions, I/O Management
	"bpmn:ServiceTask": new Set([
		"spiff_pre_post_scripts",
		"instructions",
		"ioProperties",
	]),

	// 3) Manual Task: hide Pre/Post Scripts, Instructions, Guest Options, I/O Management
	"bpmn:ManualTask": new Set([
		"spiff_pre_post_scripts",
		"instructions",
		"allow_guest_user",
		"ioProperties",
	]),

	// 4) Call Activity: hide Pre/Post Scripts, Instructions
	"bpmn:CallActivity": new Set([
		"spiff_pre_post_scripts",
		"instructions",
	]),

	// 5) Task (generic): hide Pre/Post Scripts
	"bpmn:Task": new Set([
		"spiff_pre_post_scripts",
	]),

	// 6) Script Task: hide I/O Management
	"bpmn:ScriptTask": new Set([
		"ioProperties",
	]),
};

export default function PropertiesPanelFilter(propertiesPanel) {
	this.getGroups = function (element) {
		return function (groups) {
			// Find the most specific matching type.
			// Check concrete sub-types first, fall back to generic bpmn:Task last.
			const typesToCheck = [
				"bpmn:UserTask",
				"bpmn:ServiceTask",
				"bpmn:ManualTask",
				"bpmn:CallActivity",
				"bpmn:ScriptTask",
				"bpmn:Task",
			];

			let hiddenIds = null;
			for (const type of typesToCheck) {
				if (is(element, type)) {
					hiddenIds = HIDDEN_GROUPS[type];
					break;
				}
			}

			if (!hiddenIds) {
				return groups;
			}

			return groups.filter((group) => !hiddenIds.has(group.id));
		};
	};

	propertiesPanel.registerProvider(LOWEST_PRIORITY, this);
}

PropertiesPanelFilter.$inject = ["propertiesPanel"];
