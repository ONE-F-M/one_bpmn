import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { RecordCombobox } from "../shared/RecordCombobox";
import { WorkflowStateCreatePanel } from "./WorkflowStateCreatePanel";

// Loaded once per page and shared by every Apply Workflow task; a created state is appended.
let STATES = null;
let STATES_LOADING = null;

function loadStates() {
	if (!STATES_LOADING) {
		STATES_LOADING = frappeGet("/api/resource/Workflow State", {
			fields: '["name","style"]',
			limit_page_length: 0,
			order_by: "name asc",
		}).then((rows) => {
			STATES = Array.isArray(rows) ? rows : [];
			return STATES;
		});
	}
	return STATES_LOADING.then(() => STATES);
}

export function WorkflowStateField({ id, label, value, translate, onChange }) {
	return h(RecordCombobox, {
		id,
		label,
		value,
		translate,
		onChange,
		showDots: true,
		loadOptions: loadStates,
		recordLabel: translate("Workflow State"),
		placeholder: translate("Choose a state, or type a new one"),
		emptyText: translate("No state matches"),
		newLabel: translate("New workflow state"),
		missingText: translate("This state does not exist yet, so the step will fail."),
		renderCreate: ({ initialName, onCreated, onCancel }) =>
			h(WorkflowStateCreatePanel, {
				id,
				translate,
				initialName,
				onCancel,
				onCreated: (record) => {
					STATES = [...(STATES || []), record];
					onCreated(record);
				},
			}),
	});
}
