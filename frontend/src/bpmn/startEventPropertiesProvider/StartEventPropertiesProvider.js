import { makeProvider } from "../shared/makePropertiesProvider";
import { StartEventProps } from "./StartEventProps";

// A plain start event has no event definitions (not timer, message, signal and so on).
const hasNoEventDefinitions = (element) =>
	(element.businessObject.eventDefinitions || []).length === 0;

export default {
	__init__: ["startEventPropertiesProvider"],
	startEventPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:StartEvent",
			"spiffworkflow-trigger-configuration",
			"Trigger Configuration",
			StartEventProps,
			{ when: hasNoEventDefinitions },
		),
	],
};
