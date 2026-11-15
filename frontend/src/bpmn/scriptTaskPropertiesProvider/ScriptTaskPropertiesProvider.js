import { makeProvider } from "../shared/makePropertiesProvider";
import { ScriptTaskProps } from "./ScriptTaskProps";

export default {
	__init__: ["scriptTaskPropertiesProvider"],
	scriptTaskPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:ScriptTask",
			"scriptConfiguration",
			"Script Configuration",
			ScriptTaskProps,
			{
				tooltip:
					"Link a Frappe Server Script to execute when this task runs. " +
					"The script has access to the full workflow context.",
			},
		),
	],
};
