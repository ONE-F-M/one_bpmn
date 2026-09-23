/**
 * releasedPanel — what a released property panel may change.
 *
 * "Release Property Panel" lets an authorised user edit flow object properties
 * on a locked map. The rule is that a panel edit may change what a step DOES,
 * never what the map IS, and these are the carve-outs that enforce it:
 * one_bpmn/api/property_panel.py applies the same ones again on save, and its
 * header explains each. Keep the two lists in step.
 *
 * Two callers here: the command-stack guard, which decides whether an edit is
 * allowed through, and the panel's own CSS class, which decides whether the
 * fields look editable at all. A locked element must fail both — a field that
 * accepts typing and then discards it is worse than one that never opened.
 */

// A sequence flow is not here: its condition and name are exactly the kind of
// non-breaking correction a released panel exists for. A wrong condition takes
// the wrong branch, but the map still compiles and editing again puts it right.
const LOCKED_TYPES = ["bpmn:ScriptTask"];

const LOCKED_ATTRS = ["id", "serviceType", "calledElement", "default"];

export const AI_AGENT_SERVICE_TYPE = "ai_agent";

/** Commands the properties panel uses to write a property. */
export const PROPERTY_COMMANDS = ["element.updateProperties", "element.updateModdleProperties"];

/** Is this element's panel off limits even while the panel is released? */
export function isLockedElement(bo) {
	if (!bo) return true;
	if (LOCKED_TYPES.includes(bo.$type)) return true;
	// An AI Agent Task is a Service Task wearing a serviceType.
	return bo.$type === "bpmn:ServiceTask" && bo.get("spiffworkflow:serviceType") === AI_AGENT_SERVICE_TYPE;
}

/** May this property be written? `key` may carry a namespace prefix. */
export function isEditableProperty(key) {
	const name = String(key).split(":").pop();
	return !LOCKED_ATTRS.includes(name) && !name.toLowerCase().includes("script");
}

/**
 * Is this the condition of a flow or conditional event? The panel announces the
 * expression itself as the moddle element with no properties, so match by identity.
 */
export function isConditionUpdate(bo, moddleElement) {
	if (!bo || !moddleElement) return false;
	if (bo.$type === "bpmn:SequenceFlow") return moddleElement === bo.conditionExpression;
	return (bo.eventDefinitions || []).some(
		(definition) => definition.$type === "bpmn:ConditionalEventDefinition" && definition.condition === moddleElement
	);
}

/** The single element whose panel is showing, or null. */
export function panelElement(selection) {
	return selection && selection.length === 1 ? selection[0] : null;
}
