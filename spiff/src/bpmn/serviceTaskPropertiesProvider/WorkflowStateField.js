import { h } from "preact";
import { cachedRecordList } from "../shared/cachedRecordList";
import { RecordCombobox } from "../shared/RecordCombobox";
import { WorkflowStateCreatePanel } from "./WorkflowStateCreatePanel";

const STATES = cachedRecordList("Workflow State", ["name", "style"]);

export function WorkflowStateField({ id, label, value, translate, onChange }) {
	return h(RecordCombobox, {
		id,
		label,
		value,
		translate,
		onChange,
		showDots: true,
		loadOptions: STATES.load,
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
					STATES.add(record);
					onCreated(record);
				},
			}),
	});
}
