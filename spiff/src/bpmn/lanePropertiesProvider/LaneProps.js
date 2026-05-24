import { h } from "preact";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet } from "../shared/frappeResource";

export function LaneProps(props) {
	const { element } = props;

	return [
		{
			id: "lane-role",
			element,
			component: LaneRoleComponent,
		},
	];
}

function LaneRoleComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = bo.name || "";

	const handleChange = (val) => {
		modeling.updateProperties(element, { name: val || undefined });
	};

	const fetchRoles = (txt) => {
		const filters = [["disabled", "=", 0]];
		if (txt) {
			filters.push(["name", "like", `%${txt}%`]);
		}
		return frappeGet("/api/resource/Role", {
			fields: '["name"]',
			filters: JSON.stringify(filters),
			limit_page_length: 50,
			order_by: "name asc",
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Role"),
		value,
		onChange: handleChange,
		fetchApi: fetchRoles,
		valueField: "name",
		renderOption: (opt) => opt.name,
		noResultsText: translate("No active roles found"),
	});
}
