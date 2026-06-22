import { SelectEntry, isSelectEntryEdited, CheckboxEntry, isCheckboxEntryEdited, TextFieldEntry, isTextFieldEntryEdited, TextAreaEntry, isTextAreaEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";

// Helpers
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

// Main entry — Notification Configuration group
export function NotificationProps(props) {
	const { element } = props;
	const bo             = getBusinessObject(element);
	const notifyAssignee = getAttr(bo, "notifyAssignee");

	const entries = [
		{
			id: "spiffworkflow-notifyAssignee",
			element,
			component: NotifyAssigneeComponent,
			isEdited: isCheckboxEntryEdited,
		},
	];

	if (notifyAssignee === "true") {
		entries.push(
			{
				id: "spiffworkflow-notifyTemplate",
				element,
				component: NotifyTemplateComponent,
				isEdited: isSelectEntryEdited,
			},
			{
				id: "spiffworkflow-notifySubject",
				element,
				component: NotifySubjectComponent,
				isEdited: isTextFieldEntryEdited,
			},
			{
				id: "spiffworkflow-notifyBody",
				element,
				component: NotifyBodyComponent,
				isEdited: isTextAreaEntryEdited,
			}
		);
	}

	return entries;
}

// Component 1 — Notify Assignee (checkbox)
function NotifyAssigneeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const checked = getAttr(bo, "notifyAssignee") === "true";

	const handleChange = (e) => {
		const isChecked = e.target.checked;
		const updates = {
			"spiffworkflow:notifyAssignee": isChecked ? "true" : undefined,
		};
		// When unchecked, clear the other notify fields
		if (!isChecked) {
			updates["spiffworkflow:notifyTemplate"] = undefined;
			updates["spiffworkflow:notifySubject"]  = undefined;
			updates["spiffworkflow:notifyBody"]     = undefined;
		}
		modeling.updateModdleProperties(element, bo, updates);
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: "bio-properties-panel-checkbox" },
			[
				h("label", { class: "bio-properties-panel-label", style: "display:flex;align-items:center;gap:8px;cursor:pointer;" }, [
					h("input", {
						type: "checkbox",
						checked,
						onChange: handleChange,
					}),
					translate("Notify Assignee"),
				]),
				h(
					"div",
					{ class: "bio-properties-panel-description" },
					translate("Send an interactive email notification when this task is assigned.")
				),
			]
		)
	);
}

// Component 2 — Email Template (autocomplete, visible when notifyAssignee === "true")
function NotifyTemplateComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "notifyTemplate");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:notifyTemplate": val || undefined,
		});

		// When a template is selected, fetch its subject and response to pre-fill
		if (val) {
			frappeGet(`/api/resource/Email Template/${encodeURIComponent(val)}`, {
				fields: '["subject","response"]',
			}).then((data) => {
				if (!data) return;
				const updates = {};
				// Only pre-fill if the field is currently empty
				if (!getAttr(bo, "notifySubject") && data.subject) {
					updates["spiffworkflow:notifySubject"] = data.subject;
				}
				if (!getAttr(bo, "notifyBody") && data.response) {
					updates["spiffworkflow:notifyBody"] = data.response;
				}
				if (Object.keys(updates).length > 0) {
					modeling.updateModdleProperties(element, bo, updates);
				}
			});
		}
	};

	const fetchTemplates = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/Email Template", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Email Template"),
		value,
		onChange: handleChange,
		fetchApi: fetchTemplates,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// Component 3 — Subject (text input, visible when notifyAssignee === "true")
function NotifySubjectComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "notifySubject");

	const handleInput = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:notifySubject": e.target.value || undefined,
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: "bio-properties-panel-textfield" },
			[
				h(
					"label",
					{ for: id, class: "bio-properties-panel-label" },
					translate("Subject")
				),
				h("input", {
					id,
					type: "text",
					class: "bio-properties-panel-input",
					value,
					onInput: handleInput,
					autoComplete: "off",
					spellCheck: "false",
				}),
			]
		)
	);
}

// Component 4 — Email Body (textarea, visible when notifyAssignee === "true")
function NotifyBodyComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "notifyBody");

	const handleInput = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:notifyBody": e.target.value || undefined,
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: "bio-properties-panel-textfield" },
			[
				h(
					"label",
					{ for: id, class: "bio-properties-panel-label" },
					translate("Email Body")
				),
				h("textarea", {
					id,
					class: "bio-properties-panel-input",
					style: "min-height:120px;resize:vertical;",
					value,
					onInput: handleInput,
					spellCheck: "false",
				}),
			]
		)
	);
}
