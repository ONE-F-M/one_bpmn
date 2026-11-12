export default class CommentContextPadProvider {
	constructor(contextPad, eventBus) {
		this._contextPad = contextPad;
		this._eventBus = eventBus;

		contextPad.registerProvider(this);
	}

	getContextPadEntries(element) {
		const { _eventBus: eventBus } = this;

		// Don't show on root process
		if (!element.parent) return;

		return {
			"add-comment": {
				group: "model",
				className: "bpmn-icon-comment",
				title: "Add Comment",
				action: {
					click: (event, element) => {
						eventBus.fire("commentContextPad.addComment", { element, event });
					}
				}
			}
		};
	}
}

CommentContextPadProvider.$inject = ["contextPad", "eventBus"];
