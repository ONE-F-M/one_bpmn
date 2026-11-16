import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { makeProvider } from "../shared/makePropertiesProvider";
import { AiAgentProps } from "./AiAgentProps";

const isAiAgent = (element) =>
	(getBusinessObject(element).get("spiffworkflow:serviceType") ?? "") === "ai_agent";

export default {
	__init__: ["aiAgentPropertiesProvider"],
	aiAgentPropertiesProvider: [
		"type",
		makeProvider("bpmn:ServiceTask", "AIAgentConfiguration", "AI Agent Task", AiAgentProps, {
			when: isAiAgent,
		}),
	],
};
