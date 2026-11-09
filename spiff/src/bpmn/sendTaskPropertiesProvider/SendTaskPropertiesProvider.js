import { makeProvider } from "../shared/makePropertiesProvider";
import { SendTaskProps } from "./SendTaskProps";

export default {
	__init__: ["sendTaskPropertiesProvider"],
	sendTaskPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:SendTask",
			"NotificationConfiguration",
			"Notification Configuration",
			SendTaskProps,
		),
	],
};
