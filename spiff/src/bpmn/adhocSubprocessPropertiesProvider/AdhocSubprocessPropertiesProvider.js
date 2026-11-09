import { makeProvider } from "../shared/makePropertiesProvider";
import { AdhocSubprocessProps } from "./AdhocSubprocessProps";

export default {
	__init__: ["adhocSubprocessPropertiesProvider"],
	adhocSubprocessPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:AdHocSubProcess",
			"AdhocSubprocessConfiguration",
			"Ad-hoc Subprocess",
			AdhocSubprocessProps,
		),
	],
};
