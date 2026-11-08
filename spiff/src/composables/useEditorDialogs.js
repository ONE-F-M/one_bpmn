export function useEditorDialogs(ed) {
	const { messageDialog } = ed;

	function onMessageDialogSave(close) {
		const { name, elementId, _eventBus } = messageDialog.value;
		const trimmedName = name?.trim();
		if (!trimmedName || !_eventBus) return;

		_eventBus.fire("spiff.add_message.returned", {
			name: trimmedName,
			elementId: elementId,
			correlation_properties: {},
		});
		close();
	}

	Object.assign(ed, { onMessageDialogSave });
}
