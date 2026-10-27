import { h } from "preact";
import { frappePost } from "../shared/frappeResource";
import { RecordCombobox } from "../shared/RecordCombobox";
import { createBpmnSignalMaster, findOrCreateSignal } from "./signalPick";
import { SIGNALS } from "./signalRecords";

async function createSignal(name) {
	const created = await createBpmnSignalMaster(frappePost, name);
	SIGNALS.add({ name: created });
	return created;
}

function getEventDefinition(element) {
	return element.businessObject.eventDefinitions.find((d) => d.$type === "bpmn:SignalEventDefinition");
}

// Replaces the library's signal select; a plain function, as hook-based panel entries break under this bundled Preact.
export function signalSelect(translate) {
	return function SignalSelect({ element, moddle, commandStack }) {
		const eventDefinition = getEventDefinition(element);
		const onChange = (name) => {
			eventDefinition.set("signalRef", name ? findOrCreateSignal(eventDefinition, moddle, name) : undefined);
			commandStack.execute("element.updateProperties", { element, moddleElement: element.businessObject, properties: {} });
		};
		return h(RecordCombobox, {
			id: "signal-select",
			label: translate("Signal"),
			value: eventDefinition.signalRef?.name || "",
			translate,
			onChange,
			keepTyped: true,
			loadOptions: SIGNALS.load,
			createRecord: createSignal,
			recordLabel: translate("BPMN Signal Master"),
			placeholder: translate("Choose or type a signal"),
			emptyText: translate("No signal matches"),
			missingText: translate("Not in BPMN Signal Master yet, so deploy will flag it."),
		});
	};
}
