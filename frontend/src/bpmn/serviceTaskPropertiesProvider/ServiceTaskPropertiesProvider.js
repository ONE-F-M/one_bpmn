import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { makeProvider } from "../shared/makePropertiesProvider";
import { ServiceTaskProps } from "./ServiceTaskProps";

// AI Agent Tasks get their own group from aiAgentPropertiesProvider.
const isNotAiAgent = (element) =>
	(getBusinessObject(element).get("spiffworkflow:serviceType") ?? "") !== "ai_agent";

export default {
	__init__: ["serviceTaskPropertiesProvider"],
	serviceTaskPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:ServiceTask",
			"ServiceConfiguration",
			"Service Configuration",
			ServiceTaskProps,
			{ when: isNotAiAgent },
		),
	],
};
