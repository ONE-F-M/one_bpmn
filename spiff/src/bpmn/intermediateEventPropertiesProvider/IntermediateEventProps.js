import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";

// ---------------------------------------------------------------------------
// Shared REST helper — uses native fetch for /api/resource/* endpoints
// ---------------------------------------------------------------------------
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
// Autocomplete Component
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
		if (this.props.fetchData) {
			this.props.fetchData(txt)
				.then((list) => {
					this.setState({ options: list || [], loading: false, isOpen: true });
				})
				.catch((err) => {
					console.error("Autocomplete error:", err);
					this.setState({ loading: false });
				});
		} else {
			this.setState({ loading: false });
		}
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
		const { label, id } = this.props;
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
								style: "position: absolute; z-index: 1000; background: white; border: 1px solid #ccc; width: 100%; max-height: 200px; overflow-y: auto; list-style: none; padding: 0; margin: 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);",
							},
							loading
								? [
										h(
											"li",
											{ style: "padding: 8px; color: #666;" },
											"Loading..."
										),
								  ]
								: options.length === 0
								? [
										h(
											"li",
											{ style: "padding: 8px; color: #666;" },
											"No results found"
										),
								  ]
								: options.map((opt) =>
										h(
											"li",
											{
												style: "padding: 8px; cursor: pointer; border-bottom: 1px solid #eee; background: white;",
												onMouseDown: () => this.onSelect(opt.value || opt.name),
												onMouseEnter: (e) => (e.target.style.background = "#f0f0f0"),
												onMouseLeave: (e) => (e.target.style.background = "white"),
											},
											opt.label || opt.name
										)
								  )
						),
				]),
			]
		);
	}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

// ---------------------------------------------------------------------------
// Public entry factory
// ---------------------------------------------------------------------------
export function IntermediateEventProps(props) {
	const { element } = props;

	const entries = [
		{
			id: "spiffworkflow-targetDoctype",
			element,
			component: TargetDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerWorkflow",
			element,
			component: WorkflowAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerWorkflowState",
			element,
			component: WorkflowStateAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-assignmentRule",
			element,
			component: AssignmentRuleAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	return entries;
}

// ---------------------------------------------------------------------------
// Component 1 — Target DocType
// ---------------------------------------------------------------------------
function TargetDoctypeAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "targetDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:targetDoctype": val || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
			"spiffworkflow:assignmentRule": undefined,
		});
	};

	const fetchData = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/DocType", params).then(data => 
			Array.isArray(data) ? data : []
		);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Target DocType"),
		value,
		onChange: handleChange,
		fetchData,
	});
}

// ---------------------------------------------------------------------------
// Component 2 — Workflow
// ---------------------------------------------------------------------------
function WorkflowAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value = getAttr(bo, "triggerWorkflow");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflow": val || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
	};

	const fetchData = (txt) => {
		if (!doctype) return Promise.resolve([]);
		const filters = [
			["document_type", "=", doctype],
			["is_active", "=", 1],
		];
		if (txt) {
			filters.push(["name", "like", `%${txt}%`]);
		}
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			filters: JSON.stringify(filters)
		};
		return frappeGet("/api/resource/Workflow", params).then(data => 
			Array.isArray(data) ? data : []
		);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Workflow"),
		value,
		onChange: handleChange,
		fetchData,
	});
}

// ---------------------------------------------------------------------------
// Component 3 — Workflow State
// ---------------------------------------------------------------------------
function WorkflowStateAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const workflowName = getAttr(bo, "triggerWorkflow");
	const value = getAttr(bo, "triggerWorkflowState");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflowState": val || undefined,
		});
	};

	const fetchData = (txt) => {
		if (!workflowName) return Promise.resolve([]);
		return frappeGet(`/api/resource/Workflow/${encodeURIComponent(workflowName)}`).then(doc => {
			const states = doc.states || [];
			const txtLower = (txt || "").toLowerCase();
			return states
				.filter(s => s.state.toLowerCase().includes(txtLower))
				.map(s => ({ name: s.state, label: s.state }));
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Workflow State"),
		value,
		onChange: handleChange,
		fetchData,
	});
}

// ---------------------------------------------------------------------------
// Component 4 — Assignment Rule
// ---------------------------------------------------------------------------
function AssignmentRuleAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value = getAttr(bo, "assignmentRule");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assignmentRule": val || undefined,
		});
	};

	const fetchData = (txt) => {
		if (!doctype) return Promise.resolve([]);
		const filters = [
			["document_type", "=", doctype],
			["disabled", "=", 0],
		];
		if (txt) {
			filters.push(["name", "like", `%${txt}%`]);
		}
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			filters: JSON.stringify(filters)
		};
		return frappeGet("/api/resource/Assignment Rule", params).then(data => 
			Array.isArray(data) ? data : []
		);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Assignment Rule"),
		value,
		onChange: handleChange,
		fetchData,
	});
}
