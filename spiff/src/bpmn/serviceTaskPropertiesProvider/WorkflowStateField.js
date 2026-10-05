import { h, Component } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { fixedDropdownStyle } from "../shared/dropdownPosition";
import { filterWorkflowStates } from "./workflowStateCreate";
import { WorkflowStateCreatePanel } from "./WorkflowStateCreatePanel";
import { CHECK, CHEVRON, CLOSE, PLUS, dot, icon } from "./workflowStateIcons";

// Loaded once per page and shared by every Apply Workflow task; a created state is appended.
let STATES = null;
let STATES_LOADING = null;

function loadStates() {
	if (!STATES_LOADING) {
		STATES_LOADING = frappeGet("/api/resource/Workflow State", {
			fields: '["name","style"]',
			limit_page_length: 0,
			order_by: "name asc",
		}).then((rows) => {
			STATES = Array.isArray(rows) ? rows : [];
			return STATES;
		});
	}
	return STATES_LOADING;
}

// A class component that renders plain elements only: hook-based panel entries break under this bundled Preact.
export class WorkflowStateField extends Component {
	constructor(props) {
		super(props);
		this.state = {
			open: false,
			mode: "list",
			query: "",
			typed: false,
			active: 0,
			states: STATES,
			newName: "",
		};
		this.onDocumentDown = this.onDocumentDown.bind(this);
		this.onReposition = this.onReposition.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.onDocumentDown);
		document.addEventListener("scroll", this.onReposition, true);
		window.addEventListener("resize", this.onReposition);
		// Loaded up front so the field can show the current state's colour and flag a missing one.
		loadStates().then((states) => this.setState({ states })).catch(() => this.setState({ states: [] }));
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.onDocumentDown);
		document.removeEventListener("scroll", this.onReposition, true);
		window.removeEventListener("resize", this.onReposition);
	}

	onDocumentDown(e) {
		if (!this.state.open) return;
		if (this.root?.contains(e.target) || this.menu?.contains(e.target)) return;
		this.close();
	}

	onReposition(e) {
		if (this.state.open && !(this.menu && e?.target && this.menu.contains(e.target))) this.forceUpdate();
	}

	open() {
		if (this.state.open) return;
		const selected = (this.state.states || []).findIndex((s) => s.name === this.props.value);
		this.setState({ open: true, mode: "list", query: "", typed: false, active: Math.max(selected, 0) });
	}

	close() {
		this.setState({ open: false, mode: "list", query: "", typed: false });
	}

	componentDidUpdate(prevProps, prevState) {
		// Opening scrolls the current state into view, so the list starts where the user already is.
		if (this.state.open && !prevState.open) this.menu?.querySelector(".wfs-item--active")?.scrollIntoView({ block: "center" });
	}

	select(name) {
		this.props.onChange(name);
		this.close();
		this.input?.blur();
	}

	startCreate(name) {
		this.setState({ open: true, mode: "create", newName: name || "" });
	}

	onCreated(name, style) {
		STATES = [...(STATES || []), { name, style }].sort((a, b) => a.name.localeCompare(b.name));
		this.setState({ states: STATES });
		this.select(name);
	}

	visible() {
		const { query, typed, states } = this.state;
		return filterWorkflowStates(states || [], typed ? query : "");
	}

	onKeyDown(e) {
		const { open, active, query, typed } = this.state;
		if (e.key === "Escape") {
			if (open) {
				e.preventDefault();
				this.close();
			}
			return;
		}
		if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
			e.preventDefault();
			this.open();
			return;
		}
		if (!open) return;
		const { matches, canCreate } = this.visible();
		const count = matches.length + (canCreate ? 1 : 0);
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			const step = e.key === "ArrowDown" ? 1 : -1;
			this.setState({ active: count ? (active + step + count) % count : 0 });
		} else if (e.key === "Enter") {
			e.preventDefault();
			if (active < matches.length) this.select(matches[active].name);
			else if (canCreate) this.startCreate(typed ? query.trim() : "");
		}
	}

	renderField() {
		const { value, id, translate } = this.props;
		const { open, query, typed, states } = this.state;
		const current = (states || []).find((s) => s.name === value);
		return h("div", { class: `wfs-field${open ? " wfs-field--open" : ""}` }, [
			value && !typed && dot(current?.style),
			h("input", {
				id,
				ref: (el) => (this.input = el),
				class: "wfs-input",
				type: "text",
				role: "combobox",
				"aria-expanded": open ? "true" : "false",
				"aria-controls": `${id}-menu`,
				autoComplete: "off",
				spellcheck: "false",
				placeholder: translate("Choose a state, or type a new one"),
				value: typed ? query : value || "",
				onFocus: () => this.open(),
				onClick: () => this.open(),
				onInput: (e) => this.setState({ open: true, mode: "list", query: e.target.value, typed: true, active: 0 }),
				onKeyDown: (e) => this.onKeyDown(e),
			}),
			value &&
				!typed &&
				h(
					"button",
					{
						type: "button",
						class: "wfs-icon",
						title: translate("Clear"),
						"aria-label": translate("Clear"),
						onMouseDown: (e) => e.preventDefault(),
						onClick: () => this.props.onChange(""),
					},
					icon(CLOSE)
				),
			h(
				"button",
				{
					type: "button",
					tabIndex: -1,
					class: `wfs-icon wfs-icon--chevron${open ? " wfs-icon--flip" : ""}`,
					"aria-label": translate("Show states"),
					onMouseDown: (e) => e.preventDefault(),
					onClick: () => (open ? this.close() : (this.input?.focus(), this.open())),
				},
				icon(CHEVRON)
			),
		]);
	}

	renderSupport() {
		const { value, translate } = this.props;
		const { states, open } = this.state;
		if (open || !value || !states || states.some((s) => s.name === value)) return null;
		return h("div", { class: "wfs-support wfs-support--warn" }, [
			translate("This state does not exist yet, so the step will fail. "),
			h(
				"button",
				{ type: "button", class: "wfs-link", onClick: () => this.startCreate(value) },
				translate("Create it")
			),
		]);
	}

	renderList() {
		const { value, translate } = this.props;
		const { active, states, query, typed } = this.state;
		if (!states) return h("div", { class: "wfs-empty" }, translate("Loading states…"));
		const { matches, canCreate } = this.visible();
		const items = matches.map((s, i) =>
			h(
				"li",
				{
					key: s.name,
					role: "option",
					"aria-selected": s.name === value ? "true" : "false",
					class: `wfs-item${i === active ? " wfs-item--active" : ""}${s.name === value ? " wfs-item--selected" : ""}`,
					onMouseDown: (e) => e.preventDefault(),
					onMouseEnter: () => this.setState({ active: i }),
					onClick: () => this.select(s.name),
				},
				[dot(s.style), h("span", { class: "wfs-item-label" }, s.name), s.name === value && icon(CHECK)]
			)
		);
		return [
			h("ul", { class: "wfs-list", role: "listbox", id: `${this.props.id}-menu` }, items),
			!matches.length && h("div", { class: "wfs-empty" }, translate("No state matches")),
			h("div", { class: "wfs-divider" }),
			h(
				"button",
				{
					type: "button",
					class: `wfs-create-row${active === matches.length && canCreate ? " wfs-item--active" : ""}`,
					onMouseDown: (e) => e.preventDefault(),
					onClick: () => this.startCreate(canCreate ? query.trim() : ""),
				},
				[
					icon(PLUS),
					canCreate && typed
						? h("span", null, [translate("Create"), " ", h("strong", null, `“${query.trim()}”`)])
						: h("span", null, translate("New workflow state")),
				]
			),
		];
	}

	render() {
		const { id, label } = this.props;
		const { open, mode } = this.state;
		return h("div", { class: "bio-properties-panel-entry wfs", "data-entry-id": id, ref: (el) => (this.root = el) }, [
			h("label", { for: id, class: "bio-properties-panel-label" }, label),
			this.renderField(),
			this.renderSupport(),
			open &&
				h(
					"div",
					{
						class: "wfs-menu",
						ref: (el) => (this.menu = el),
						style: fixedDropdownStyle(this.input?.parentElement, mode === "create" ? 320 : 280),
					},
					mode === "create"
						? h(WorkflowStateCreatePanel, {
								id,
								translate: this.props.translate,
								initialName: this.state.newName,
								onCreated: (name, style) => this.onCreated(name, style),
								onCancel: () => this.setState({ mode: "list" }),
						  })
						: this.renderList()
				),
		]);
	}
}
