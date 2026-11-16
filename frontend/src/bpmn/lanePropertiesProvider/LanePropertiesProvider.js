import { makeProvider } from "../shared/makePropertiesProvider";
import { LaneProps } from "./LaneProps";

export default {
	__init__: ["lanePropertiesProvider"],
	lanePropertiesProvider: [
		"type",
		makeProvider("bpmn:Lane", "LaneRoleConfiguration", "Lane Role", LaneProps, {
			prepend: true,
		}),
	],
};
