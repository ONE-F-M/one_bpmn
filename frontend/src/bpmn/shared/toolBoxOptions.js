// Every ad-hoc sub-process in the diagram that can hold an agent's tools, as select options.
export function toolBoxOptions(businessObjects, currentId, translate) {
	const boxes = new Map();
	for (const bo of businessObjects) {
		if (bo?.$type === "bpmn:AdHocSubProcess" && bo.get("spiffworkflow:serviceType") !== "ai_task_selector") {
			boxes.set(bo.id, bo);
		}
	}
	const options = [
		{ value: "", label: translate("No tools") },
		...[...boxes.values()].map((bo) => ({ value: bo.id, label: bo.name ? `${bo.name} (${bo.id})` : bo.id })),
	];
	if (currentId && !boxes.has(currentId)) {
		options.push({ value: currentId, label: `${currentId} ${translate("(not in this diagram)")}` });
	}
	return options;
}
