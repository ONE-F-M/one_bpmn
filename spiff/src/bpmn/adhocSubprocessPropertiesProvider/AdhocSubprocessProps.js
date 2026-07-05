import {
	TextFieldEntry,
	isTextFieldEntryEdited,
	CheckboxEntry,
	isCheckboxEntryEdited,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";

/**
 * Property entries for a bpmn:AdHocSubProcess element.
 *
 * Both properties are standard BPMN 2.0 (no moddle extension needed):
 *   - completionCondition — a contained bpmn:FormalExpression child element
 *   - cancelRemainingInstances — a Boolean attribute, spec default true
 *
 * The engine-side parser (_AdHocProcessParser, WI-001348) reads exactly this
 * shape: an unqualified cancelRemainingInstances attribute and the
 * <bpmn:completionCondition> child's text.
 */
export function AdhocSubprocessProps(props) {
	const { element } = props;

	return [
		{
			id: "adhoc-completionCondition",
			element,
			component: CompletionConditionComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "adhoc-cancelRemainingInstances",
			element,
			component: CancelRemainingInstancesComponent,
			isEdited: isCheckboxEntryEdited,
		},
	];
}

function CompletionConditionComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const bpmnFactory = useService("bpmnFactory");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const getValue = () => bo.get("completionCondition")?.body ?? "";

	const setValue = (value) => {
		if (!value) {
			// Clearing the field removes the child element entirely so the
			// diagram XML stays free of empty <bpmn:completionCondition/> tags.
			modeling.updateModdleProperties(element, bo, { completionCondition: undefined });
			return;
		}
		const existing = bo.get("completionCondition");
		if (existing) {
			modeling.updateModdleProperties(element, existing, { body: value });
		} else {
			const expression = bpmnFactory.create("bpmn:FormalExpression", { body: value });
			expression.$parent = bo;
			modeling.updateModdleProperties(element, bo, { completionCondition: expression });
		}
	};

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Completion Condition"),
		description: translate(
			"Expression evaluated after each inner task completes; the subprocess ends when it is true."
		),
		getValue,
		setValue,
		debounce: useService("debounceInput"),
	});
}

function CancelRemainingInstancesComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	// BPMN spec default is true; moddle omits the attribute when set to true.
	const getValue = () => bo.get("cancelRemainingInstances") !== false;

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			cancelRemainingInstances: value ? undefined : false,
		});
	};

	return h(CheckboxEntry, {
		element,
		id,
		label: translate("Cancel Remaining Instances"),
		description: translate(
			"When the completion condition becomes true, cancel inner tasks that are still running instead of letting them finish."
		),
		getValue,
		setValue,
	});
}
