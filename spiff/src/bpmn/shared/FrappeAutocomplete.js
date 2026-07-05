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
import { fixedDropdownStyle } from "./dropdownPosition";
import "./bpmn-panel.css";

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
		this.inputRef = null;
		this.listRef = null;
		this.debounceTimer = null;
		this.handleDocumentClick = this.handleDocumentClick.bind(this);
		this.handleScroll = this.handleScroll.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.handleDocumentClick);
		// The list is position:fixed so it can escape the panel's overflow
		// clipping — reposition it when anything scrolls (capture phase
		// catches the panel's inner scroll containers too).
		document.addEventListener("scroll", this.handleScroll, true);
		window.addEventListener("resize", this.handleScroll);
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.handleDocumentClick);
		document.removeEventListener("scroll", this.handleScroll, true);
		window.removeEventListener("resize", this.handleScroll);
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
	}

	handleScroll(e) {
		if (!this.state.isOpen) return;
		// Scrolling inside the dropdown itself must not trigger a reposition
		if (this.listRef && e.target && this.listRef.contains(e.target)) return;
		this.forceUpdate();
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

	_listStyle() {
		return fixedDropdownStyle(this.inputRef);
	}

	render() {
		const { label, id, renderOption, valueField = "name", noResultsText } = this.props;
		const { isOpen, options, loading, searchTxt } = this.state;

		const getVal = (opt) => opt[valueField] || opt.name;
		const getLabel = renderOption || ((opt) => opt.label || opt.name);

		return h(
			"div",
			{ class: "bio-properties-panel-entry", "data-entry-id": id, ref: (c) => (this.containerRef = c) },
			[
				h("div", { class: "bio-properties-panel-textfield bpmn-dropdown-wrap" }, [
					label && h("label", { for: id, class: "bio-properties-panel-label" }, label),
					h("input", {
						id: id,
						type: "text",
						class: "bio-properties-panel-input",
						value: searchTxt,
						ref: (el) => (this.inputRef = el),
						onInput: (e) => this.onInput(e),
						onFocus: () => this.onFocus(),
						autoComplete: "off",
						spellCheck: "false",
					}),
					isOpen &&
						h(
							"ul",
							{
								class: "bpmn-dropdown-list",
								style: this._listStyle(),
								ref: (el) => (this.listRef = el),
							},
							[
								loading && h("li", { class: "bpmn-dropdown-loading" }, "Loading..."),
								!loading &&
									options.length === 0 &&
									h("li", { class: "bpmn-dropdown-empty" }, noResultsText || "No results found"),
								!loading &&
									options.map((opt) =>
										h(
											"li",
											{
												key: getVal(opt),
												class: "bpmn-dropdown-item",
												onMouseDown: (e) => {
													e.preventDefault();
													this.onSelect(getVal(opt), opt);
												},
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
