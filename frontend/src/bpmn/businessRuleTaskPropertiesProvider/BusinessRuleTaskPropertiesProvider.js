import { makeProvider } from "../shared/makePropertiesProvider";
import { BusinessRuleTaskProps } from "./BusinessRuleTaskProps";

export default {
	__init__: ["businessRuleTaskPropertiesProvider"],
	businessRuleTaskPropertiesProvider: [
		"type",
		makeProvider(
			"bpmn:BusinessRuleTask",
			"businessRuleConfiguration",
			"Business Rule Properties",
			BusinessRuleTaskProps,
			{
				tooltip:
					"Link a Frappe-stored DMN decision table to execute when this Business Rule Task runs.",
			},
		),
	],
};
