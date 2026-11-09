import { markRaw } from "vue";
import { frappeRequest } from "frappe-ui";
import { decodeHtmlAttr, encodeHtmlAttr } from "@/bpmn/shared/htmlAttrCodec";
import { NOTIFY_EDITOR_ATTRS, contextDoctype } from "@/bpmn/shared/notifyAssigneeAttrs";

export function useEditorSpiffEvents(ed) {
	const { props, emit, messageDialog, aiAgentModal } = ed;

	ed.onReady(async () => {
		const eventBus = ed.modeler.get("eventBus");
		// --- SpiffWorkflow EventBus Integration ---
		// These handlers are required for the spiffworkflow properties panel
		// "Launch Editor" buttons and data-request dropdowns to function.

		// Script editing (Script Tasks, Pre/Post scripts)
		eventBus.on("spiff.script.edit", (event) => {
			emit("launch-script-editor", {
				element: event.element,
				scriptType: event.scriptType,
				script: event.script || "",
				eventBus: event.eventBus,
				readonly: props.readonly,
			});
		});

		eventBus.on("spiff.markdown.edit", (event) => {
			emit("launch-markdown-editor", {
				element: event.element,
				value: event.value || "",
				eventBus: event.eventBus,
			});
		});

		eventBus.on("spiff.callactivity.edit", (event) => {
			emit("launch-callactivity-editor", {
				processId: event.processId,
				element: event.element,
			});
		});

		eventBus.on("spiff.callactivity.search", (event) => {
			emit("launch-callactivity-search", {
				processId: event.processId,
				eventBus: event.eventBus,
				element: event.element,
			});
		});

		eventBus.on("spiff.file.edit", () => {
			// Not implemented - file editing is handled externally
		});

		eventBus.on("spiff.dmn.edit", (event) => {
			// SpiffExtensionLaunchButton fires { value, eventBus } - it does NOT
			// include the element. Resolve it from the modeler's selection.
			const selection = ed.modeler.get("selection");
			const selected = selection.get();
			const element = selected?.length === 1 ? selected[0] : null;
			emit("launch-dmn-editor", {
				element,
				value: event.value || "",
				eventBus: event.eventBus,
			});
		});

		// AI Agent Task / AI Task Selector config modal
		eventBus.on("launch-ai-agent-editor", (event) => {
			aiAgentModal.value = {
				show: true,
				element: markRaw(event.element),
				mode: event.mode || "agent",
			};
		});

		// Notification editing (Send Tasks)
		eventBus.on("spiff.notification.edit", (event) => {
			emit("launch-notification-editor", {
				element: event.element,
				notificationName: event.notificationName || "",
				eventBus: event.eventBus,
			});
		});

		// Write notification name back to BPMN element when dialog resolves
		eventBus.on("spiff.notification.update", (event) => {
			if (event.element && event.notificationName) {
				const modeling = ed.modeler.get("modeling");
				const bo = event.element.businessObject || event.element;
				modeling.updateModdleProperties(event.element, bo, {
					"spiffworkflow:notificationName": event.notificationName,
				});
			}
		});

		// Notify Assignee editor (User Tasks)
		eventBus.on("spiff.userTask.notifyAssignee.edit", (event) => {
			const bo = event.element.businessObject || event.element;
			emit("launch-notify-assignee-editor", {
				element: event.element,
				values: {
					...event.values,
					notifyAssigneeBody: decodeHtmlAttr(event.values.notifyAssigneeBody) || "",
				},
				doctype: contextDoctype(bo),
				taskName: bo.name || bo.id,
				taskActions: event.taskActions,
				eventBus: event.eventBus,
			});
		});

		// Write every Notification Editor value back to the BPMN element in one update
		eventBus.on("spiff.userTask.notifyAssignee.update", (event) => {
			if (event.element) {
				const modeling = ed.modeler.get("modeling");
				const bo = event.element.businessObject || event.element;
				const updates = {};
				for (const name of NOTIFY_EDITOR_ATTRS) {
					const value = event.values[name];
					updates[`spiffworkflow:${name}`] =
						name === "notifyAssigneeBody" ? encodeHtmlAttr(value) : value || undefined;
				}
				modeling.updateModdleProperties(event.element, bo, updates);
			}
		});

		// Email Notification editor (Service Tasks): the dialog edits a copy, Save sends the changed attributes
		eventBus.on("spiff.serviceTask.emailNotification.edit", (event) => {
			emit("launch-email-notification-editor", {
				element: event.element,
				values: {
					...event.values,
					emailBody: decodeHtmlAttr(event.values.emailBody) || "",
				},
				eventBus: event.eventBus,
			});
		});

		eventBus.on("spiff.serviceTask.emailNotification.update", (event) => {
			const bo = event.element.businessObject || event.element;
			const updates = {};
			for (const name of event.changed) {
				const value = event.values[name];
				updates[`spiffworkflow:${name}`] =
					name === "emailBody" ? encodeHtmlAttr(value) : value || undefined;
			}
			if (Object.keys(updates).length)
				ed.modeler.get("modeling").updateModdleProperties(event.element, bo, updates);
		});

		eventBus.on("spiff.service_tasks.requested", (event) => {
			event.eventBus.fire("spiff.service_tasks.returned", {
				serviceTaskOperators: [],
			});
		});

		eventBus.on("spiff.json_schema_files.requested", (event) => {
			event.eventBus.fire("spiff.json_schema_files.returned", {
				options: [],
			});
		});

		eventBus.on("spiff.dmn_files.requested", async (event) => {
			let options = [];
			if (props.modelName) {
				try {
					const resp = await frappeRequest({
						url: "/api/method/one_bpmn.api.dmn.get_decision_list",
						params: { process_model: props.modelName },
					});
					// frappeRequest auto-unwraps "message"; resp is the list directly
					const decisions = Array.isArray(resp) ? resp : resp?.message || [];
					options = decisions.map((d) => ({
						label: d.decision_name || d.decision_id,
						value: d.decision_id,
					}));
				} catch (err) {
					console.warn("[BpmnEditor] Failed to fetch DMN files:", err);
				}
			}
			event.eventBus.fire("spiff.dmn_files.returned", { options });
		});

		eventBus.on("spiff.data_stores.requested", (event) => {
			event.eventBus.fire("spiff.data_stores.returned", {
				options: [],
			});
		});

		eventBus.on("spiff.messages.requested", (event) => {
			// Read existing <bpmn:message> elements from the definitions
			const definitions = ed.modeler.getDefinitions();
			const rootElements = definitions?.rootElements || [];
			const messages = rootElements
				.filter((el) => el.$type === "bpmn:Message")
				.map((msg) => ({ identifier: msg.name, name: msg.name }));
			event.eventBus.fire("spiff.messages.returned", {
				configuration: { messages },
			});
		});

		// Message editing (IntermediateCatchEvent, ReceiveTask)
		// When the BA clicks "Open message editor" on a catch event,
		// show a frappe-ui Dialog to type/edit the message name.
		// On save, fire spiff.add_message.returned which creates the
		// <bpmn:Message> element and wires it to the catch event.
		eventBus.on("spiff.message.edit", (event) => {
			messageDialog.value.isEdit = true;
			messageDialog.value.name = event.value?.messageId || "";
			messageDialog.value.elementId = event.value?.elementId || "";
			messageDialog.value._eventBus = event.eventBus;
			messageDialog.value.show = true;
		});

		// Handle "add new message" from the MessageSelect dropdown
		eventBus.on("spiff.add_message.requested", (event) => {
			messageDialog.value.isEdit = false;
			messageDialog.value.name = "";
			messageDialog.value.elementId = "";
			messageDialog.value._eventBus = event.eventBus;
			messageDialog.value.show = true;
		});

		eventBus.on("spiff.msg_json_schema_files.requested", (event) => {
			event.eventBus.fire("spiff.msg_json_schema_files.returned", { options: [] });
		});
	});
}
