/**
 * FrappeAutocomplete.js
 *
 * Reusable Preact class-based autocomplete dropdown for the bpmn-js
 * properties panel.  Supports two data-fetching styles:
 *
 *   1. `fetchApi(txt)`: returns Promise<Array<object>>.
 *      Pair with `valueField` (default "name") and `renderOption(opt)`.
 *
 *   2. Inline `/api/resource/DocType`-only mode: if `fetchApi` is NOT
 *      provided, the component queries DocTypes directly (legacy compat).
 *
 * Props:
 *   - id          {string}
 *   - label       {string}
 *   - value       {string}
 *   - onChange     {function(string, object=)}  — called with (value) on input,
 *                                                  or (value, option) on selection
 *   - fetchApi     {function(string): Promise<Array>}  — preferred
 *   - valueField   {string}   — key in option objects (default "name")
 *   - renderOption  {function(object): string}  — display renderer
 *   - noResultsText {string}  — empty-state message (default "No results found")
 */

import { h, Component } from "preact";
import { frappeGet } from "./frappeResource";

export class FrappeAutocomplete extends Component {
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

	// -----------------------------------------------------------------
	// Data fetching
	// -----------------------------------------------------------------
	fetchOptions(txt) {
		this.setState({ loading: true });

		const promise = this.props.fetchApi
			? this.props.fetchApi(txt)
			: this._defaultFetchDocTypes(txt);

		promise
			.then((list) => {
				this.setState({ options: list || [], loading: false, isOpen: true });
			})
			.catch((err) => {
				console.error("[FrappeAutocomplete] fetch error:", err);
				this.setState({ loading: false });
			});
	}

	/** Fallback: query `/api/resource/DocType` when no fetchApi prop. */
	_defaultFetchDocTypes(txt) {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/DocType", params).then((data) =>
			Array.isArray(data) ? data : []
		);
	}

	// -----------------------------------------------------------------
	// Event handlers
	// -----------------------------------------------------------------
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

	onSelect(val, opt) {
		this.setState({ searchTxt: val, isOpen: false });
		this.props.onChange(val, opt);
	}

	// -----------------------------------------------------------------
	// Render
	// -----------------------------------------------------------------
	render() {
		const { label, id, renderOption, valueField = "name", noResultsText } = this.props;
		const { isOpen, options, loading, searchTxt } = this.state;

		const getVal = (opt) => opt[valueField] || opt.name;
		const getLabel = renderOption || ((opt) => opt.label || opt.name);

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
									h(
										"li",
										{ style: "padding: 8px; color: #666; font-size: 13px;" },
										noResultsText || "No results found"
									),
								!loading &&
									options.map((opt) =>
										h(
											"li",
											{
												key: getVal(opt),
												style: "padding: 8px; font-size: 13px; cursor: pointer; border-bottom: 1px solid #eee;",
												onMouseDown: (e) => {
													e.preventDefault();
													this.onSelect(getVal(opt), opt);
												},
												onMouseEnter: (e) => (e.target.style.background = "#f3f4f6"),
												onMouseLeave: (e) => (e.target.style.background = "white"),
											},
											getLabel(opt)
										)
									),
							]
						),
				]),
			]
		);
	}
}
