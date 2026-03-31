import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";

// Shared REST helper
function frappeGet(path, params = {}) {
	const qs = Object.entries(params)
		.filter(([, v]) => v !== undefined && v !== null)
		.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
		.join("&");
	const url = qs ? `${path}?${qs}` : path;
	return fetch(url, { credentials: "include" })
		.then((r) => r.json())
		.then((json) => {
			if (json.data !== undefined) return json.data;
			if (json.message !== undefined) return json.message;
			return json;
		});
}

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
// Generic Frappe Autocomplete Component 
// ---------------------------------------------------------------------------
class FrappeAutocomplete extends Component {
	constructor(props) {
		super(props);
		this.state = {
			isOpen: false,
			options: [],
			loading: false,
			searchTxt: props.value || "",
		};
		this.containerRef = null;
		this.debounceTimer = null;
		this.handleDocumentClick = this.handleDocumentClick.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.handleDocumentClick);
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.handleDocumentClick);
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
	}

	componentDidUpdate(prevProps) {
		if (prevProps.value !== this.props.value && this.props.value !== this.state.searchTxt) {
			this.setState({ searchTxt: this.props.value || "" });
		}
	}

	handleDocumentClick(e) {
		if (this.containerRef && !this.containerRef.contains(e.target)) {
			this.setState({ isOpen: false });
		}
	}

	fetchOptions(txt) {
		this.setState({ loading: true });
		this.props.fetchApi(txt)
			.then((list) => {
				this.setState({ options: list || [], loading: false, isOpen: true });
			})
			.catch((err) => {
				console.error("[UserTask] Autocomplete error:", err);
				this.setState({ loading: false });
			});
	}

	onFocus() {
		this.fetchOptions(this.state.searchTxt);
	}

	onInput(e) {
		const val = e.target.value;
		this.setState({ searchTxt: val, isOpen: true });

		if (this.debounceTimer) clearTimeout(this.debounceTimer);
		this.debounceTimer = setTimeout(() => {
			this.fetchOptions(val);
		}, 300);

		this.props.onChange(val);
	}

	onSelect(val) {
		this.setState({ searchTxt: val, isOpen: false });
		this.props.onChange(val);
	}

	render() {
		const { label, id, renderOption, valueField } = this.props;
		const { isOpen, options, loading, searchTxt } = this.state;

		return h(
			"div",
			{ class: "bio-properties-panel-entry", "data-entry-id": id, ref: (c) => (this.containerRef = c) },
			[
				h("div", { class: "bio-properties-panel-textfield", style: "position: relative;" }, [
					h("label", { for: id, class: "bio-properties-panel-label" }, label),
					h("input", {
						id: id,
						type: "text",
						class: "bio-properties-panel-input",
						value: searchTxt,
						onInput: (e) => this.onInput(e),
						onFocus: () => this.onFocus(),
						autoComplete: "off",
						spellCheck: "false",
					}),
					isOpen &&
						h(
							"ul",
							{
								class: "bio-properties-panel-dropdown",
								style:
									"position: absolute; top: calc(100% + 4px); left: 0; right: 0; max-height: 200px; overflow-y: auto; background: white; border: 1px solid #ccc; border-radius: 4px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 1000; margin: 0; padding: 0; list-style: none;",
							},
							[
								loading && h("li", { style: "padding: 8px; color: #666; font-size: 13px;" }, "Loading..."),
								!loading &&
									options.length === 0 &&
									h("li", { style: "padding: 8px; color: #666; font-size: 13px;" }, "No options found"),
								!loading &&
									options.map((opt) =>
										h(
											"li",
											{
												key: opt[valueField],
												style: "padding: 8px; font-size: 13px; cursor: pointer; border-bottom: 1px solid #eee;",
												onMouseDown: (e) => {
													e.preventDefault();
													this.onSelect(opt[valueField]);
												},
												onMouseEnter: (e) => (e.target.style.background = "#f3f4f6"),
												onMouseLeave: (e) => (e.target.style.background = "white"),
											},
											renderOption(opt)
										)
									),
							]
						),
				]),
			]
		);
	}
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
