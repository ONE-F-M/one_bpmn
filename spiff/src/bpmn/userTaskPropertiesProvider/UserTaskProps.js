import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element, bo) {
	const mode = bo.get("spiffworkflow:assigneeMode");
	modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:assigneeMode": mode,
	});
}

// ---------------------------------------------------------------------------
// Properties UI Provider
// ---------------------------------------------------------------------------

export function UserTaskProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);
	const assigneeMode = getAttr(bo, "assigneeMode");

	const entries = [
		{
			id: "spiffworkflow-assigneeMode",
			element,
			component: AssigneeModeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (assigneeMode === "User") {
		entries.push({
			id: "spiffworkflow-assigneeUser",
			element,
			component: AssigneeUserAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		});
	} else if (assigneeMode === "Docfield") {
		entries.push({
			id: "spiffworkflow-targetDoctype",
			element,
			component: TargetDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-assigneeDocfield",
			element,
			component: AssigneeDocfieldAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		});
	}

	return entries;
}

// Component 1 - Assignee Mode
function AssigneeModeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const getValue = () => getAttr(bo, "assigneeMode");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeMode": value || undefined,
			"spiffworkflow:targetDoctype": undefined,
			"spiffworkflow:assigneeUser": undefined,
			"spiffworkflow:assigneeDocfield": undefined,
		});
	};

	const getOptions = () => [
		{ label: translate("-- Select Assignee Mode --"), value: "" },
		{ label: translate("User"), value: "User" },
		{ label: translate("Docfield"), value: "Docfield" },
	];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Assignee Mode"),
		getValue,
		setValue,
		getOptions,
	});
}

// Component 2 - Assignee User (Autocomplete)
function AssigneeUserAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "assigneeUser");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeUser": val || undefined,
		});
	};

	const fetchUsers = (txt) => {
		const filters = [
			["user_type", "=", "System User"],
			["enabled", "=", 1],
		];
		if (txt) {
			filters.push(["full_name", "like", `%${txt}%`]);
		}
		return frappeGet("/api/resource/User", {
			fields: '["name","full_name"]',
			filters: JSON.stringify(filters),
			limit_page_length: 50,
			order_by: "full_name asc",
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Assignee User"),
		value,
		onChange: handleChange,
		fetchApi: fetchUsers,
		valueField: "name",
		renderOption: (opt) => `${opt.full_name} (${opt.name})`,
	});
}

// Component 3 - Target Doctype (Autocomplete)
function TargetDoctypeAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "targetDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:targetDoctype": val || undefined,
			"spiffworkflow:assigneeDocfield": undefined,
		});
	};

	const fetchDoctypes = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/DocType", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Target DocType"),
		value,
		onChange: handleChange,
		fetchApi: fetchDoctypes,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// Component 4 - Assignee Docfield (Autocomplete)
function AssigneeDocfieldAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value = getAttr(bo, "assigneeDocfield");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeDocfield": val || undefined,
		});
	};

	const fetchDocfields = (txt) => {
		if (!doctype) {
			return Promise.resolve([{ fieldname: "", label: "-- Select Target DocType First --" }]);
		}
		return frappeGet("/api/method/one_bpmn.api.get_assignee_docfields", { doctype })
			.then((fields) => {
				const list = Array.isArray(fields) ? fields : [];
				if (!txt) return list;
				// Filter client-side since RPC doesn't accept txt filter
				const lowerTxt = txt.toLowerCase();
				return list.filter(
					(f) =>
						(f.fieldname && f.fieldname.toLowerCase().includes(lowerTxt)) ||
						(f.label && f.label.toLowerCase().includes(lowerTxt))
				);
			});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Assignee Docfield"),
		value,
		onChange: handleChange,
		fetchApi: fetchDocfields,
		valueField: "fieldname",
		renderOption: (opt) =>
			opt.fieldname ? `${opt.label || opt.fieldname} (${opt.fieldname})` : opt.label,
	});
}
