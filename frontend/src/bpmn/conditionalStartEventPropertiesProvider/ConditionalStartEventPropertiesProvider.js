import { makeProvider } from "../shared/makePropertiesProvider";
import { ConditionalStartEventProps } from "./ConditionalStartEventProps";

const hasConditionalDefinition = (element) =>
	(element.businessObject.eventDefinitions || []).some(
		(e) => e.$type === "bpmn:ConditionalEventDefinition",
	);

export default {
	__init__: ["conditionalStartEventPropertiesProvider"],
	conditionalStartEventPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:StartEvent",
			"spiffworkflow-conditional-trigger-configuration",
			"Trigger Configuration",
			ConditionalStartEventProps,
			{ when: hasConditionalDefinition },
		),
	],
};
