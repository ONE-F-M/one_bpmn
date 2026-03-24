/**
 * StartEventProps.js
 *
 * Trigger Configuration entries for plain Start Events.
 */

import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";

// ---------------------------------------------------------------------------
// Shared REST helper — uses native fetch for /api/resource/* endpoints
// frappeRequest is designed for frappe.call() whitelisted methods (returns
// {message: ...}). The REST resource API returns {data: [...]}, so we use
// fetch directly to avoid response transformation issues.
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
// Async Caches for standard dropdowns
// ---------------------------------------------------------------------------
const _workflowCache = new Map();
const _workflowFetching = new Set();
const _workflowStateCache = new Map();
const _workflowStateFetching = new Set();

function loadWorkflows(doctype, onLoaded) {
	if (!doctype) return;
	if (_workflowCache.has(doctype)) {
		onLoaded(_workflowCache.get(doctype));
		return;
	}
	if (_workflowFetching.has(doctype)) return;
	_workflowFetching.add(doctype);

	frappeGet("/api/resource/Workflow", {
		fields: '["name"]',
		filters: JSON.stringify([
			["document_type", "=", doctype],
			["is_active", "=", 1],
		]),
		limit_page_length: 100,
	})
		.then((data) => {
			const list = Array.isArray(data) ? data : [];
			const options = [
				{ label: "-- Select Workflow --", value: "" },
				...list.map((d) => ({ label: d.name, value: d.name })),
			];
			_workflowCache.set(doctype, options);
			_workflowFetching.delete(doctype);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[StartEvent] fetch Workflows:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_workflowCache.set(doctype, err);
			_workflowFetching.delete(doctype);
			onLoaded(err);
		});
}

function loadWorkflowStates(workflowName, onLoaded) {
	if (!workflowName) return;
	if (_workflowStateCache.has(workflowName)) {
		onLoaded(_workflowStateCache.get(workflowName));
		return;
	}
	if (_workflowStateFetching.has(workflowName)) return;
	_workflowStateFetching.add(workflowName);

	frappeGet(`/api/resource/Workflow/${encodeURIComponent(workflowName)}`)
		.then((doc) => {
			const states = (doc && doc.states) ? doc.states : [];
			const options = [
				{ label: "-- Select State --", value: "" },
				...states.map((s) => ({ label: s.state, value: s.state })),
			];
			_workflowStateCache.set(workflowName, options);
			_workflowStateFetching.delete(workflowName);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[StartEvent] fetch Workflow States:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_workflowStateCache.set(workflowName, err);
			_workflowStateFetching.delete(workflowName);
			onLoaded(err);
		});
}

// ---------------------------------------------------------------------------
// Frappe-like Autocomplete — Preact Class Component (avoids hooks issues)
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
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		frappeGet("/api/resource/DocType", params)
			.then((data) => {
				const list = Array.isArray(data) ? data : [];
				this.setState({ options: list, loading: false, isOpen: true });
			})
			.catch((err) => {
				console.error("[StartEvent] Autocomplete error:", err);
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
								class: "bio-properties-panel-dropdown",
								style:
									"position: absolute; top: calc(100% + 4px); left: 0; right: 0; max-height: 200px; overflow-y: auto; background: white; border: 1px solid #ccc; border-radius: 4px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 1000; margin: 0; padding: 0; list-style: none;",
							},
							[
								loading && h("li", { style: "padding: 8px; color: #666; font-size: 13px;" }, "Loading..."),
								!loading &&
									options.length === 0 &&
									h("li", { style: "padding: 8px; color: #666; font-size: 13px;" }, "No DocTypes found"),
								!loading &&
									options.map((opt) =>
										h(
											"li",
											{
												key: opt.name,
												style: "padding: 8px; font-size: 13px; cursor: pointer; border-bottom: 1px solid #eee;",
												onMouseDown: (e) => {
													e.preventDefault();
													this.onSelect(opt.name);
												},
												onMouseEnter: (e) => (e.target.style.background = "#f3f4f6"),
												onMouseLeave: (e) => (e.target.style.background = "white"),
											},
											opt.name
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
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element, bo) {
	const triggerType = bo.get("spiffworkflow:triggerType");
	modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:triggerType": triggerType,
	});
}

// ---------------------------------------------------------------------------
// Public entry factory
// ---------------------------------------------------------------------------
export function StartEventProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);
	const triggerType = getAttr(bo, "triggerType");

	const entries = [
		{
			id: "spiffworkflow-triggerDoctype",
			element,
			component: TriggerDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerType",
			element,
			component: TriggerTypeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (triggerType === "Workflow State") {
		entries.push({
			id: "spiffworkflow-triggerWorkflow",
			element,
			component: TriggerWorkflowComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-triggerWorkflowState",
			element,
			component: TriggerWorkflowStateComponent,
			isEdited: isSelectEntryEdited,
		});
	}

	return entries;
}

// ---------------------------------------------------------------------------
// Component 1 — Trigger DocType (Searchable Autocomplete)
// ---------------------------------------------------------------------------
function TriggerDoctypeAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "triggerDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerDoctype": val || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});

		if (val) {
			loadWorkflows(val, () => touchElement(modeling, element, bo));
		}
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Trigger DocType"),
		value,
		onChange: handleChange,
	});
}

// ---------------------------------------------------------------------------
// Component 2 — Trigger Type
// ---------------------------------------------------------------------------
function TriggerTypeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const getValue = () => getAttr(bo, "triggerType");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerType": value || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
	};

	const getOptions = () => [
		{ label: translate("-- Select Trigger Type --"), value: "" },
		{ label: translate("After Insert"), value: "After Insert" },
		{ label: translate("Workflow State"), value: "Workflow State" },
	];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Trigger Type"),
		getValue,
		setValue,
		getOptions,
	});
}

// ---------------------------------------------------------------------------
// Component 3 — Workflow
// ---------------------------------------------------------------------------
function TriggerWorkflowComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "triggerDoctype");

	if (doctype && !_workflowCache.has(doctype) && !_workflowFetching.has(doctype)) {
		loadWorkflows(doctype, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "triggerWorkflow");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflow": value || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
		if (value) {
			loadWorkflowStates(value, () => touchElement(modeling, element, bo));
		}
	};

	const getOptions = () =>
		_workflowCache.get(doctype) || [
			{
				label: doctype ? translate("Loading...") : translate("-- Select DocType first --"),
				value: "",
			},
		];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Workflow"),
		getValue,
		setValue,
		getOptions,
	});
}

// ---------------------------------------------------------------------------
// Component 4 — Workflow State
// ---------------------------------------------------------------------------
function TriggerWorkflowStateComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const workflowName = getAttr(bo, "triggerWorkflow");

	if (
		workflowName &&
		!_workflowStateCache.has(workflowName) &&
		!_workflowStateFetching.has(workflowName)
	) {
		loadWorkflowStates(workflowName, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "triggerWorkflowState");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflowState": value || undefined,
		});
	};

	const getOptions = () =>
		_workflowStateCache.get(workflowName) || [
			{
				label: workflowName ? translate("Loading...") : translate("-- Select Workflow first --"),
				value: "",
			},
		];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Workflow State"),
		getValue,
		setValue,
		getOptions,
	});
}
