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
							style: [
								"border: 1px solid #ccc",
								"border-radius: 4px",
								"padding: 4px 6px",
								"min-height: 38px",
								"display: flex",
								"flex-wrap: wrap",
								"align-items: center",
								"gap: 4px",
								"cursor: text",
								"background: #fff",
							].join(";"),
							onClick: () => this.inputRef && this.inputRef.focus(),
						},
						[
							// Selected tags
							...selected.map((val) =>
								h(
									"span",
									{
										key: val,
										style: [
											"display: inline-flex",
											"align-items: center",
											"gap: 3px",
											"background: #e8f4fd",
											"border: 1px solid #b8d8f0",
											"border-radius: 3px",
											"padding: 2px 6px",
											"font-size: 12px",
											"line-height: 16px",
										].join(";"),
									},
									[
										h("span", { style: "max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" }, val),
										h(
											"button",
											{
												type: "button",
												title: "Remove",
												onMouseDown: (e) => {
													e.preventDefault();
													this.remove(val);
												},
												style: [
													"background: none",
													"border: none",
													"cursor: pointer",
													"padding: 0 0 0 2px",
													"line-height: 1",
													"font-size: 14px",
													"color: #666",
													"font-weight: bold",
												].join(";"),
											},
											"×"
										),
									]
								)
							),

							// Input for searching + adding
							h(
								"div",
								{ style: "position: relative; flex: 1; min-width: 80px;" },
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
										style: [
											"border: none",
											"outline: none",
											"width: 100%",
											"font-size: 13px",
											"background: transparent",
											"padding: 2px 0",
										].join(";"),
									}),

									// Dropdown
									isOpen &&
										h(
											"ul",
											{
												style: [
													"position: absolute",
													"top: calc(100% + 2px)",
													"left: 0",
													"min-width: 220px",
													"max-height: 200px",
													"overflow-y: auto",
													"background: white",
													"border: 1px solid #ccc",
													"border-radius: 4px",
													"box-shadow: 0 4px 8px rgba(0,0,0,0.12)",
													"z-index: 1000",
													"margin: 0",
													"padding: 0",
													"list-style: none",
												].join(";"),
											},
											[
												loading &&
													h(
														"li",
														{ style: "padding: 8px; color: #666; font-size: 13px;" },
														"Loading…"
													),
												!loading &&
													options.length === 0 &&
													h(
														"li",
														{ style: "padding: 8px; color: #999; font-size: 13px;" },
														"No results found"
													),
												!loading &&
													options.map((opt) =>
														h(
															"li",
															{
																key: getVal(opt),
																style: [
																	"padding: 8px 10px",
																	"font-size: 13px",
																	"cursor: pointer",
																	"border-bottom: 1px solid #f0f0f0",
																].join(";"),
																onMouseDown: (e) => {
																	e.preventDefault();
																	this.add(getVal(opt));
																},
																onMouseEnter: (e) =>
																	(e.currentTarget.style.background = "#f3f6fa"),
																onMouseLeave: (e) =>
																	(e.currentTarget.style.background = "white"),
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
							{ style: "font-size: 11px; color: #888; margin-top: 3px;" },
							`${selected.length} user${selected.length > 1 ? "s" : ""} selected`
						),
				]
			)
		);
	}
}
