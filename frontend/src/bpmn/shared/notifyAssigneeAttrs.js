/**
 * Every spiffworkflow attribute the Notification Editor reads and writes on a
 * User Task. The moddle registration, the panel button, the save handler and
 * the Notify Assignee checkbox all use this one list.
 */
export const NOTIFY_EDITOR_ATTRS = [
	"notifyAssigneeBody",
	"notifyAssigneeSubject",
	"notifyAssigneeTemplate",
	"notifyLayout",
	"notifySubjectAr",
	"notifyQuestionEn",
	"notifyQuestionAr",
	"notifyFacts",
	"notifyDetails",
	"notifyAttachments",
	"notifyActions",
	"notifyConversation",
	"notifyTokenHours",
	"notifyArabicEdited",
];

export const NOTIFY_LAYOUTS = ["card", "steps", "chat"];

/** A task sends the Email Template or custom HTML unless a layout was picked. */
export function isHtmlMode(notifyLayout) {
	return !NOTIFY_LAYOUTS.includes(notifyLayout);
}

/** The process start event's trigger DocType, else the task's own target DocType. */
export function contextDoctype(userTaskBo) {
	let parent = userTaskBo.$parent;
	while (parent && parent.$type !== "bpmn:Process") parent = parent.$parent;
	for (const el of parent?.flowElements || []) {
		if (el.$type !== "bpmn:StartEvent") continue;
		const trigger =
			el.get?.("spiffworkflow:triggerDoctype") ||
			el.$attrs?.["spiffworkflow:triggerDoctype"] ||
			(el.eventDefinitions || []).map((d) => d.$attrs?.["spiffworkflow:triggerDoctype"]).find(Boolean);
		if (trigger) return trigger;
	}
	return userTaskBo.get?.("spiffworkflow:targetDoctype") || userTaskBo.$attrs?.["spiffworkflow:targetDoctype"] || "";
}
