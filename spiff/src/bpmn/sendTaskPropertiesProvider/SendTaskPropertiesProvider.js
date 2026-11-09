import { makeProvider } from "../shared/makePropertiesProvider";
import { SendTaskProps } from "./SendTaskProps";

export default makeProvider(
	"bpmn:SendTask",
	"NotificationConfiguration",
	"Notification Configuration",
	SendTaskProps,
);
