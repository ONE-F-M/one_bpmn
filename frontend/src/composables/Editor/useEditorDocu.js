import { computed, markRaw } from "vue";

export function useEditorDocu(ed) {
	const { props, docuPanel } = ed;

	// Human-readable BPMN shape type, and what the DocType *is* at this step (derived
	// from the property field the Launch-Docu button was placed on). Threaded to the
	// agent so it designs a DocType that fits this exact step + its role in the flow.
	function _elementTypeLabel(bo) {
		const t = (bo?.$type || "").replace(/^bpmn:/, "");
		const map = {
			StartEvent: "start event",
			UserTask: "user task (a step a person completes)",
			ServiceTask: "automated service task",
			SendTask: "notification step",
			ScriptTask: "script step",
			BusinessRuleTask: "decision step",
			Task: "task",
		};
		return (
			map[t] ||
			(t
				? t
						.replace(/([A-Z])/g, " $1")
						.trim()
						.toLowerCase()
				: "step")
		);
	}

	const _DOCTYPE_FIELD_ROLES = {
		triggerDoctype: "the record whose creation or change starts this process",
		targetDoctype: "the record a person fills in or works on at this step",
		serviceTargetDoctype: "the record this automated step reads or updates",
		emailDoctype: "the record this email is about",
		updateFieldDoctype: "the record whose fields this step updates",
		pushDoctype: "the record this notification is about",
	};

	function _neighbourNames(conns, side) {
		return (conns || [])
			.map((c) => (side === "source" ? c.source : c.target)?.businessObject?.name)
			.filter(Boolean);
	}

	const docuProcessContext = computed(() => {
		const el = docuPanel.value.element;
		const bo = el?.businessObject;
		const doc = bo?.documentation?.[0];
		return {
			process_name: props.modelName || "",
			process: props.process || "",
			element_id: bo?.id || "",
			element_name: bo?.name || "",
			element_type: _elementTypeLabel(bo),
			field_role: _DOCTYPE_FIELD_ROLES[docuPanel.value.attr] || "",
			element_description: (doc?.text || doc?.$body || "").trim(),
			upstream: _neighbourNames(el?.incoming, "source"),
			downstream: _neighbourNames(el?.outgoing, "target"),
		};
	});

	// Docu applied a DocType - write its name back onto the shape's doctype field
	// through the properties-panel eventBus that launched the panel.
	function onDocuApplied(doctypeName) {
		const eb = docuPanel.value._eventBus;
		if (eb && doctypeName) {
			eb.fire("docu.doctype.update", { doctype: doctypeName });
		}
	}

	ed.onReady(() => {
		const eventBus = ed.modeler.get("eventBus");

		// Docu - AI DocType builder (launched from a doctype field's button)
		eventBus.on("launch-docu-editor", (event) => {
			docuPanel.value = {
				show: true,
				element: markRaw(event.element),
				doctype: event.doctype || "",
				attr: event.attr || "",
				_eventBus: event.eventBus || eventBus,
			};
		});
	});

	Object.assign(ed, { docuProcessContext, onDocuApplied });
}
