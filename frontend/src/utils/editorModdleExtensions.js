import { spiffModdleExtension } from "bpmn-js-spiffworkflow";
import { NOTIFY_EDITOR_ATTRS } from "@/bpmn/shared/notifyAssigneeAttrs";

export function registerSpiffExtensions() {
	// Extend spiff workflow moddle definitions to include our custom timer properties
	if (spiffModdleExtension && Array.isArray(spiffModdleExtension.types)) {
		// Timer extension (hot-reloading safety)
		const hasTimerExt = spiffModdleExtension.types.find(
			(t) => t.name === "TimerEventDefinitionExtension",
		);
		if (!hasTimerExt) {
			spiffModdleExtension.types.push({
				name: "TimerEventDefinitionExtension",
				extends: ["bpmn:TimerEventDefinition"],
				properties: [
					{ name: "cronExpression", isAttr: true, type: "String" },
					// Kept for backward compat - existing XML may contain this.
					{ name: "schedulerFrequency", isAttr: true, type: "String" },
				],
			});
		}

		// Start Event trigger extension (hot-reloading safety)
		const hasStartEventExt = spiffModdleExtension.types.find(
			(t) => t.name === "StartEventTriggerExtension",
		);
		if (!hasStartEventExt) {
			spiffModdleExtension.types.push({
				name: "StartEventTriggerExtension",
				extends: ["bpmn:StartEvent"],
				properties: [
					{ name: "triggerDoctype", isAttr: true, type: "String" },
					{ name: "triggerType", isAttr: true, type: "String" },
					{ name: "triggerWorkflow", isAttr: true, type: "String" },
					{ name: "triggerWorkflowState", isAttr: true, type: "String" },
				],
			});
		}

		// Conditional Start Event trigger extension (hot-reloading safety)
		const hasCondStartEventExt = spiffModdleExtension.types.find(
			(t) => t.name === "ConditionalEventTriggerExtension",
		);
		if (!hasCondStartEventExt) {
			spiffModdleExtension.types.push({
				name: "ConditionalEventTriggerExtension",
				extends: ["bpmn:ConditionalEventDefinition"],
				properties: [
					{ name: "triggerDoctype", isAttr: true, type: "String" },
					{ name: "triggerType", isAttr: true, type: "String" },
					{ name: "triggerWorkflow", isAttr: true, type: "String" },
					{ name: "triggerWorkflowState", isAttr: true, type: "String" },
				],
			});
		}

		// User Task assignee extension
		const hasUserTaskExt = spiffModdleExtension.types.find(
			(t) => t.name === "UserTaskAssigneeExtension",
		);
		if (!hasUserTaskExt) {
			spiffModdleExtension.types.push({
				name: "UserTaskAssigneeExtension",
				extends: ["bpmn:UserTask"],
				properties: [
					{ name: "assigneeMode", isAttr: true, type: "String" },
					{ name: "targetDoctype", isAttr: true, type: "String" },
					{ name: "assigneeUser", isAttr: true, type: "String" },
					{ name: "assigneeDocfield", isAttr: true, type: "String" },
					{ name: "assigneeUsers", isAttr: true, type: "String" },
					{ name: "assigneeTableField", isAttr: true, type: "String" },
					{ name: "assigneeTableUserField", isAttr: true, type: "String" },
					{ name: "roundRobinLastUser", isAttr: true, type: "String" },
					{ name: "taskActions", isAttr: true, type: "String" },
					{ name: "notifyAssignee", isAttr: true, type: "String" },
					...NOTIFY_EDITOR_ATTRS.map((name) => ({ name, isAttr: true, type: "String" })),
				],
			});

			spiffModdleExtension.types.push({
				name: "ScriptTaskServerScriptExtension",
				extends: ["bpmn:ScriptTask"],
				properties: [{ name: "serverScript", isAttr: true, type: "String" }],
			});
		}

		// Send Task notification extension
		const hasSendTaskExt = spiffModdleExtension.types.find(
			(t) => t.name === "SendTaskNotificationExtension",
		);
		if (!hasSendTaskExt) {
			spiffModdleExtension.types.push({
				name: "SendTaskNotificationExtension",
				extends: ["bpmn:SendTask"],
				properties: [{ name: "notificationName", isAttr: true, type: "String" }],
			});
		}

		// Service Task "Apply Workflow" extension
		const hasServiceTaskExt = spiffModdleExtension.types.find(
			(t) => t.name === "ServiceTaskApplyWorkflowExtension",
		);
		if (!hasServiceTaskExt) {
			spiffModdleExtension.types.push({
				name: "ServiceTaskApplyWorkflowExtension",
				extends: ["bpmn:ServiceTask"],
				properties: [
					{ name: "serviceType", isAttr: true, type: "String" },
					{ name: "serviceTargetDoctype", isAttr: true, type: "String" },
					{ name: "workflowState", isAttr: true, type: "String" },
					{ name: "docStatus", isAttr: true, type: "String" },
					{ name: "onlyAllowEdit", isAttr: true, type: "String" },
					{ name: "confirmTransition", isAttr: true, type: "String" },
					{ name: "emailAccount", isAttr: true, type: "String" },
					{ name: "emailUseDoctype", isAttr: true, type: "String" },
					{ name: "emailDoctype", isAttr: true, type: "String" },
					{ name: "emailSubject", isAttr: true, type: "String" },
					{ name: "emailTo", isAttr: true, type: "String" },
					{ name: "emailToDocFields", isAttr: true, type: "String" },
					{ name: "emailToTableField", isAttr: true, type: "String" },
					{ name: "emailToTableUserField", isAttr: true, type: "String" },
					{ name: "emailToRoles", isAttr: true, type: "String" },
					{ name: "emailCc", isAttr: true, type: "String" },
					{ name: "emailBcc", isAttr: true, type: "String" },
					{ name: "emailBody", isAttr: true, type: "String" },
					{ name: "emailLayout", isAttr: true, type: "String" },
					{ name: "emailSubjectAr", isAttr: true, type: "String" },
					{ name: "emailHeadingEn", isAttr: true, type: "String" },
					{ name: "emailHeadingAr", isAttr: true, type: "String" },
					{ name: "emailMessageEn", isAttr: true, type: "String" },
					{ name: "emailMessageAr", isAttr: true, type: "String" },
					{ name: "emailShowStatus", isAttr: true, type: "String" },
					{ name: "emailFacts", isAttr: true, type: "String" },
					{ name: "emailDetails", isAttr: true, type: "String" },
					{ name: "emailAttachments", isAttr: true, type: "String" },
					{ name: "emailArabicEdited", isAttr: true, type: "String" },
					{ name: "updateFieldDoctype", isAttr: true, type: "String" },
					{ name: "updateFieldName", isAttr: true, type: "String" },
					{ name: "updateFieldValue", isAttr: true, type: "String" },
					// Multi-row field update (JSON array of {field, value})
					{ name: "updateFieldRows", isAttr: true, type: "String" },
					// Google Chat attrs
					{ name: "gchatType", isAttr: true, type: "String" },
					{ name: "gchatRecipientBasis", isAttr: true, type: "String" },
					{ name: "gchatEmail", isAttr: true, type: "String" },
					{ name: "gchatDoctype", isAttr: true, type: "String" },
					{ name: "gchatDocField", isAttr: true, type: "String" },
					{ name: "gchatTableField", isAttr: true, type: "String" },
					{ name: "gchatTableUserField", isAttr: true, type: "String" },
					{ name: "gchatSpaceId", isAttr: true, type: "String" },
					{ name: "gchatMessage", isAttr: true, type: "String" },
					// Push Notification attrs
					{ name: "pushDoctype", isAttr: true, type: "String" },
					{ name: "pushTitle", isAttr: true, type: "String" },
					{ name: "pushMessage", isAttr: true, type: "String" },
					{ name: "pushToUsers", isAttr: true, type: "String" },
					{ name: "pushToDocFields", isAttr: true, type: "String" },
					{ name: "pushToRoles", isAttr: true, type: "String" },
					{ name: "pushToTableField", isAttr: true, type: "String" },
					{ name: "pushToTableUserField", isAttr: true, type: "String" },
					{ name: "pushLinkToDocument", isAttr: true, type: "String" },
					{ name: "pushFallbackInApp", isAttr: true, type: "String" },
					// AI Agent Task attrs
					{ name: "aiBackend", isAttr: true, type: "String" },
					{ name: "aiProvider", isAttr: true, type: "String" },
					{ name: "aiModel", isAttr: true, type: "String" },
					{ name: "aiOutputVariable", isAttr: true, type: "String" },
					{ name: "aiSystemPrompt", isAttr: true, type: "String" },
					{ name: "aiUserPrompt", isAttr: true, type: "String" },
					{ name: "aiResponseFormat", isAttr: true, type: "String" },
					{ name: "aiResponseSchema", isAttr: true, type: "String" },
					{ name: "aiTemperature", isAttr: true, type: "String" },
					{ name: "aiTopP", isAttr: true, type: "String" },
					{ name: "aiMaxTokens", isAttr: true, type: "String" },
					{ name: "aiTimeout", isAttr: true, type: "String" },
					{ name: "aiMaxRetries", isAttr: true, type: "String" },
					{ name: "aiWriteBackField", isAttr: true, type: "String" },
					{ name: "aiStopOnError", isAttr: true, type: "String" },
					// Connector service-task attributes
					{ name: "connectorId", isAttr: true, type: "String" },
					{ name: "operation", isAttr: true, type: "String" },
					{ name: "connectorParams", isAttr: true, type: "String" },
					{ name: "resultVariable", isAttr: true, type: "String" },
					{ name: "failOnError", isAttr: true, type: "String" },
				],
			});
		}

		// Ad-hoc Subprocess AI Task Selector extension.
		// The selector attaches to the subprocess ITSELF (not an inner
		// task): an LLM chooses which inner task/tool runs next.
		const hasAdhocSelectorExt = spiffModdleExtension.types.find(
			(t) => t.name === "AdhocAiTaskSelectorExtension",
		);
		if (!hasAdhocSelectorExt) {
			spiffModdleExtension.types.push({
				name: "AdhocAiTaskSelectorExtension",
				extends: ["bpmn:AdHocSubProcess"],
				properties: [
					{ name: "serviceType", isAttr: true, type: "String" },
					{ name: "aiProvider", isAttr: true, type: "String" },
					{ name: "aiModel", isAttr: true, type: "String" },
					{ name: "aiSystemPrompt", isAttr: true, type: "String" },
					{ name: "aiUserPrompt", isAttr: true, type: "String" },
					// "diagram" | "registry" | "both" - which tool sources
					// the selector may choose from (defaults to "both")
					{ name: "aiToolSources", isAttr: true, type: "String" },
				],
			});
		}

		// Business Rule Task decision reference extension
		const hasBusinessRuleTaskExt = spiffModdleExtension.types.find(
			(t) => t.name === "BusinessRuleTaskDecisionExtension",
		);
		if (!hasBusinessRuleTaskExt) {
			spiffModdleExtension.types.push({
				name: "BusinessRuleTaskDecisionExtension",
				extends: ["bpmn:BusinessRuleTask"],
				properties: [{ name: "calledDecisionId", isAttr: true, type: "String" }],
			});
		}

		// Sticky Note extension
		const hasStickyNoteExt = spiffModdleExtension.types.find(
			(t) => t.name === "StickyNoteExtension",
		);
		if (!hasStickyNoteExt) {
			spiffModdleExtension.types.push({
				name: "StickyNoteExtension",
				extends: ["bpmn:TextAnnotation"],
				properties: [
					{ name: "isStickyNote", isAttr: true, type: "Boolean" },
					{ name: "color", isAttr: true, type: "String" },
				],
			});
		}
	}
}
