import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { makeProvider } from "../shared/makePropertiesProvider";
import { AiTaskSelectorProps } from "./AiTaskSelectorProps";

const isAiTaskSelector = (element) =>
	(getBusinessObject(element).get("spiffworkflow:serviceType") ?? "") === "ai_task_selector";

export default {
	__init__: ["aiTaskSelectorPropertiesProvider"],
	aiTaskSelectorPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:AdHocSubProcess",
			"AiTaskSelectorConfiguration",
			"AI Task Selector",
			AiTaskSelectorProps,
			{ when: isAiTaskSelector },
		),
	],
};
