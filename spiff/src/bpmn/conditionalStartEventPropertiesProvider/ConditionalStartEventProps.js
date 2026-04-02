/**
 * ConditionalStartEventProps.js
 *
 * Trigger Configuration entries for Conditional Start Events.
 * Fields:
 *   1. Trigger DocType — searchable autocomplete (Frappe REST API)
 *   2. Trigger Type — "After Insert" or "Workflow State"
 *   3. Workflow — filtered by selected DocType (visible when type = "Workflow State")
 *   4. Workflow State — filtered by selected Workflow (visible when type = "Workflow State")
 *
 * All values are persisted as spiffworkflow: extension attributes on the
 * bpmn:ConditionalEventDefinition element so they survive XML round-trips.
 */

import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";

// ---------------------------------------------------------------------------
// Shared REST helper
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
// Async Caches
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
			console.error("[ConditionalStartEvent] fetch Workflows:", e);
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
			const states = doc && doc.states ? doc.states : [];
			const options = [
				{ label: "-- Select State --", value: "" },
				...states.map((s) => ({ label: s.state, value: s.state })),
			];
			_workflowStateCache.set(workflowName, options);
			_workflowStateFetching.delete(workflowName);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[ConditionalStartEvent] fetch Workflow States:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_workflowStateCache.set(workflowName, err);
			_workflowStateFetching.delete(workflowName);
			onLoaded(err);
		});
}

// ---------------------------------------------------------------------------
// DocType Autocomplete — Preact Class Component
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
				console.error("[ConditionalStartEvent] Autocomplete error:", err);
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
// Helpers — read/write on the ConditionalEventDefinition element
// ---------------------------------------------------------------------------
function getConditionalDef(element) {
	const bo = getBusinessObject(element);
	const eventDefs = bo.eventDefinitions || [];
	return eventDefs.find((e) => e.$type === "bpmn:ConditionalEventDefinition");
}

function getAttr(condDef, attr) {
	return condDef.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element) {
	// Force a re-render of the properties panel by doing a no-op property
	// update on the business object. This makes cached async data visible.
	const bo = getBusinessObject(element);
	const condDef = getConditionalDef(element);
	if (condDef) {
		const triggerType = condDef.get("spiffworkflow:triggerType");
		modeling.updateModdleProperties(element, condDef, {
			"spiffworkflow:triggerType": triggerType,
		});
	}
}

// ---------------------------------------------------------------------------
// Public entry factory
// ---------------------------------------------------------------------------
export function ConditionalStartEventProps(props) {
	const { element } = props;
	const condDef = getConditionalDef(element);
	if (!condDef) return [];

	const triggerType = getAttr(condDef, "triggerType");

	const entries = [
		{
			id: "spiffworkflow-cond-triggerDoctype",
			element,
			component: TriggerDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-cond-triggerType",
			element,
			component: TriggerTypeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (triggerType === "Workflow State") {
		entries.push({
			id: "spiffworkflow-cond-triggerWorkflow",
			element,
			component: TriggerWorkflowComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-cond-triggerWorkflowState",
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
	const condDef = getConditionalDef(element);

	const value = getAttr(condDef, "triggerDoctype");

	const handleChange = (val) => {
		// Clear dependent fields when doctype changes
		modeling.updateModdleProperties(element, condDef, {
			"spiffworkflow:triggerDoctype": val || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});

		// Invalidate workflow cache for the old doctype so fresh data loads
		if (val) {
			loadWorkflows(val, () => touchElement(modeling, element));
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
	const condDef = getConditionalDef(element);

	const getValue = () => getAttr(condDef, "triggerType");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, condDef, {
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
// Component 3 — Workflow (filtered by doctype)
// ---------------------------------------------------------------------------
function TriggerWorkflowComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const condDef = getConditionalDef(element);

	const doctype = getAttr(condDef, "triggerDoctype");

	if (doctype && !_workflowCache.has(doctype) && !_workflowFetching.has(doctype)) {
		loadWorkflows(doctype, () => touchElement(modeling, element));
	}

	const getValue = () => getAttr(condDef, "triggerWorkflow");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, condDef, {
			"spiffworkflow:triggerWorkflow": value || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
		if (value) {
			loadWorkflowStates(value, () => touchElement(modeling, element));
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
// Component 4 — Workflow State (filtered by workflow)
// ---------------------------------------------------------------------------
function TriggerWorkflowStateComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const condDef = getConditionalDef(element);

	const workflowName = getAttr(condDef, "triggerWorkflow");

	if (
		workflowName &&
		!_workflowStateCache.has(workflowName) &&
		!_workflowStateFetching.has(workflowName)
	) {
		loadWorkflowStates(workflowName, () => touchElement(modeling, element));
	}

	const getValue = () => getAttr(condDef, "triggerWorkflowState");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, condDef, {
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
