/**
 * Calls onLink once with the script name linked to this element and script type.
 * A dialog closed without linking leaves the listener waiting, so links made for other steps are ignored.
 */
export function listenForScriptLink(eventBus, element, scriptType, onLink) {
	const listener = (event) => {
		if (event.element?.id !== element.id || event.scriptType !== scriptType) return;
		eventBus.off("spiff.script.update", listener);
		onLink(event.script || "");
	};
	eventBus.on("spiff.script.update", listener);
}
