/**
 * FrappeMultiSelect.js
 *
 * Tag-based multi-select component for the bpmn-js properties panel.
 * Renders selected values as removable tags + an autocomplete input for adding more.
 *
 * Props:
 *   - id          {string}
 *   - label       {string}
 *   - value       {string}  — comma-separated list of selected values
 *   - onChange    {function(string)} — called with new comma-separated value
 *   - fetchApi    {function(string): Promise<Array>}
 *   - valueField  {string}  — key in option objects (default "name")
 *   - renderOption {function(object): string}
 *   - displayField {string} — key used to display existing tags (default same as valueField)
 */

import { h, Component } from "preact";
import "./bpmn-panel.css";

export class FrappeMultiSelect extends Component {
	constructor(props) {
		super(props);
		this.state = {
			inputText: "",
			options: [],
			isOpen: false,
			loading: false,
		};
		this.containerRef   = null;
		this.inputRef       = null;
		this.debounceTimer  = null;
		this.handleDocClick = this.handleDocClick.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.handleDocClick);
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.handleDocClick);
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
	}

	handleDocClick(e) {
		if (this.containerRef && !this.containerRef.contains(e.target)) {
			this.setState({ isOpen: false });
		}
	}

	// -------------------------------------------------------------------
	// Value helpers — store as comma-separated in the XML attribute
	// -------------------------------------------------------------------
	getSelected() {
		const raw = this.props.value || "";
		return raw ? raw.split(",").map((v) => v.trim()).filter(Boolean) : [];
	}

	remove(val) {
		const next = this.getSelected().filter((v) => v !== val).join(",");
		this.props.onChange(next);
	}

	add(val) {
		const current = this.getSelected();
		if (val && !current.includes(val)) {
			this.props.onChange([...current, val].join(","));
		}
		this.setState({ inputText: "", isOpen: false });
	}

	// -------------------------------------------------------------------
	// Fetch
	// -------------------------------------------------------------------
	fetchOptions(txt) {
		if (!this.props.fetchApi) return;
		this.setState({ loading: true });

		this.props.fetchApi(txt)
			.then((list) => {
				const vf       = this.props.valueField || "name";
				const selected = this.getSelected();
				// Exclude already-selected values
				const filtered = (list || []).filter((opt) => !selected.includes(opt[vf]));
				this.setState({ options: filtered, loading: false, isOpen: true });
			})
			.catch(() => this.setState({ loading: false }));
	}

	onInput(e) {
		const val = e.target.value;
		this.setState({ inputText: val });
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
		this.debounceTimer = setTimeout(() => this.fetchOptions(val), 300);
	}

	onFocus() {
		this.fetchOptions(this.state.inputText);
	}

	// -------------------------------------------------------------------
	// Render
	// -------------------------------------------------------------------
	render() {
		const {
			id,
			label,
			valueField   = "name",
			renderOption,
			itemLabel    = "item",
		} = this.props;

		const { inputText, options, isOpen, loading } = this.state;
		const selected = this.getSelected();

		const getVal   = (opt) => opt[valueField];
		const getLabel = renderOption || ((opt) => opt.label || opt[valueField] || opt.name);

		return h(
			"div",
			{
				class: "bio-properties-panel-entry",
				"data-entry-id": id,
				ref: (c) => (this.containerRef = c),
			},
			h(
				"div",
				{ class: "bio-properties-panel-textfield" },
				[
					h("label", { class: "bio-properties-panel-label" }, label),

					// ── Tag + input container ────────────────────────────────
					h(
						"div",
						{
					class: "bpmn-tag-input-wrap",
							onClick: () => this.inputRef && this.inputRef.focus(),
						},
						[
							// Selected tags
							...selected.map((val) =>
								h(
									"span",
									{
										key: val,
								class: "bpmn-tag",
									},
									[
										h("span", { class: "bpmn-tag-text" }, val),
										h(
											"button",
											{
												type: "button",
												title: "Remove",
												onMouseDown: (e) => {
													e.preventDefault();
													this.remove(val);
												},
										class: "bpmn-tag-remove",
											},
											"×"
										),
									]
								)
							),

							// Input for searching + adding
							h(
								"div",
								{ class: "bpmn-tag-input-field-wrap" },
								[
									h("input", {
										type: "text",
										id,
										value: inputText,
										placeholder: selected.length === 0 ? "Type to search…" : "",
										onInput: (e) => this.onInput(e),
										onFocus: () => this.onFocus(),
										autoComplete: "off",
										spellCheck: "false",
										ref: (c) => (this.inputRef = c),
								class: "bpmn-tag-input-field",
									}),

									// Dropdown
									isOpen &&
										h(
											"ul",
											{
										class: "bpmn-dropdown-list",
											},
											[
												loading &&
													h(
														"li",
														{ class: "bpmn-dropdown-loading" },
														"Loading…"
													),
												!loading &&
													options.length === 0 &&
													h(
														"li",
														{ class: "bpmn-dropdown-empty" },
														"No results found"
													),
												!loading &&
													options.map((opt) =>
														h(
															"li",
															{
																key: getVal(opt),
																class: "bpmn-dropdown-item",
																onMouseDown: (e) => {
																	e.preventDefault();
																	this.add(getVal(opt));
																},
															},
															getLabel(opt)
														)
													),
											]
										),
								]
							),
						]
					),

					// Helper text
					selected.length > 0 &&
						h(
							"div",
							{ class: "bio-properties-panel-description" },
							`${selected.length} ${itemLabel}${selected.length !== 1 ? "s" : ""} selected`
						),
				]
			)
		);
	}
}
