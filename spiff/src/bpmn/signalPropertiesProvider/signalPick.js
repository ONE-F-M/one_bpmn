// Linking a signal event to a BPMN Signal Master record, kept free of the panel's imports so node --test can load it.

// Resolves to the created record's name; the caller passes trimmed, non-blank text.
export function createBpmnSignalMaster(post, name) {
	// BPMN Signal Master is named by bpmn_signal_name, so the record is always called what was typed.
	return post("/api/resource/BPMN Signal Master", { bpmn_signal_name: name }).then(() => name);
}

// Resolves once the record is deleted; maps that still use the name keep it but it leaves the picker.
export function deleteBpmnSignalMaster(del, name) {
	return del(`/api/resource/BPMN Signal Master/${encodeURIComponent(name)}`);
}

function getDefinitions(businessObject) {
	let node = businessObject;
	while (node.$parent) node = node.$parent;
	return node;
}

// Returns the diagram's bpmn:Signal called name, adding it when the diagram has none.
export function findOrCreateSignal(businessObject, moddle, name) {
	const definitions = getDefinitions(businessObject);
	const existing = definitions.rootElements.find((e) => e.$type === "bpmn:Signal" && e.name === name);
	if (existing) return existing;
	const signal = moddle.create("bpmn:Signal", { id: `Signal_${Math.random().toString(36).slice(2, 9)}`, name });
	signal.$parent = definitions;
	definitions.rootElements.push(signal);
	return signal;
}
