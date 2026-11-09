import { makeProvider } from "../shared/makePropertiesProvider";
import { UserTaskProps } from "./UserTaskProps";

export default makeProvider(
	"bpmn:UserTask",
	"AssigneeConfiguration",
	"Assignment Configuration",
	UserTaskProps,
);
