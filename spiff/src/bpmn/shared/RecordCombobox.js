import { h, Component } from "preact";
import { fixedDropdownStyle } from "./dropdownPosition";
import { filterRecords } from "./recordFilter";
import { CHECK, CHEVRON, CLOSE, PLUS, dot, icon } from "./recordIcons";
import { serverMessage } from "@/utils/serverMessage";

/**
 * A searchable field for picking a record by name, with "Create" for a name that does not exist.
 * Create either opens props.renderCreate inside the menu, or calls props.createRecord(name) directly.
 * A class rendering plain elements only: hook-based panel entries break under this bundled Preact.
 */
export class RecordCombobox extends Component {
	constructor(props) {
		super(props);
		this.state = { open: false, mode: "list", query: "", typed: false, active: 0, options: null, creating: false, error: "", createName: "" };
		this.onDocumentDown = this.onDocumentDown.bind(this);
		this.onReposition = this.onReposition.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.onDocumentDown);
		document.addEventListener("scroll", this.onReposition, true);
		window.addEventListener("resize", this.onReposition);
		// Loaded up front so the field can flag a value that is not a record.
		this.props.loadOptions().then((options) => this.setState({ options })).catch(() => this.setState({ options: [] }));
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.onDocumentDown);
		document.removeEventListener("scroll", this.onReposition, true);
		window.removeEventListener("resize", this.onReposition);
	}

	componentDidUpdate(prevProps, prevState) {
		// Opening scrolls the current value into view, so the list starts where the user already is.
		if (this.state.open && !prevState.open) this.menu?.querySelector(".wfs-item--active")?.scrollIntoView({ block: "center" });
	}

	onDocumentDown(e) {
		if (!this.state.open || this.root?.contains(e.target) || this.menu?.contains(e.target)) return;
		this.commitTyped();
		this.close();
	}

	onReposition(e) {
		if (this.state.open && !(this.menu && e?.target && this.menu.contains(e.target))) this.forceUpdate();
	}

	open() {
		if (this.state.open) return;
		const selected = (this.state.options || []).findIndex((o) => o.name === this.props.value);
		this.setState({ open: true, mode: "list", query: "", typed: false, active: Math.max(selected, 0), error: "" });
	}

	close() {
		this.setState({ open: false, mode: "list", query: "", typed: false, creating: false });
	}

	// With keepTyped, text left in the box is saved as typed; the missing-record warning then offers to create it.
	commitTyped() {
		const { keepTyped, value, onChange } = this.props;
		const text = this.state.query.trim();
		if (keepTyped && this.state.typed && text && text !== value) onChange(text);
	}

	select(name) {
		this.props.onChange(name);
		this.close();
		this.input?.blur();
	}

	added(record) {
		this.setState({ options: [...(this.state.options || []), record].sort((a, b) => a.name.localeCompare(b.name)) });
		this.select(record.name);
	}

	async create(name) {
		const { renderCreate, createRecord } = this.props;
		if (renderCreate) {
			this.setState({ open: true, mode: "create", createName: name });
			return;
		}
		if (!name || this.state.creating) return;
		this.setState({ creating: true, error: "" });
		try {
			this.added({ name: await createRecord(name) });
		} catch (err) {
			this.setState({ creating: false, open: false, error: serverMessage(err) });
		}
	}

	visible() {
		const { query, typed, options } = this.state;
		return filterRecords(options || [], typed ? query : "");
	}

	onKeyDown(e) {
		const { open, active, query } = this.state;
		if (e.key === "Escape") {
			if (open) {
				e.preventDefault();
				this.close();
			}
			return;
		}
		if (!open) {
			if (e.key === "ArrowDown") {
				e.preventDefault();
				this.open();
			}
			return;
		}
		const { matches, canCreate } = this.visible();
		const count = matches.length + (canCreate ? 1 : 0);
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			this.setState({ active: count ? (active + (e.key === "ArrowDown" ? 1 : -1) + count) % count : 0 });
		} else if (e.key === "Enter") {
			e.preventDefault();
			if (active < matches.length) this.select(matches[active].name);
			else if (canCreate) this.create(query.trim());
		} else if (e.key === "Tab") {
			this.commitTyped();
			this.close();
		}
	}

	renderField() {
		const { value, id, translate, placeholder, showDots } = this.props;
		const { open, query, typed, options } = this.state;
		const current = (options || []).find((o) => o.name === value);
		return h("div", { class: `wfs-field${open ? " wfs-field--open" : ""}` }, [
			showDots && value && !typed && dot(current?.style),
			h("input", {
				id,
				ref: (el) => (this.input = el),
				class: "wfs-input",
				type: "text",
				role: "combobox",
				"aria-expanded": open ? "true" : "false",
				"aria-controls": `${id}-menu`,
				autoComplete: "off",
				spellcheck: false,
				placeholder,
				value: typed ? query : value || "",
				onFocus: () => this.open(),
				onClick: () => this.open(),
				onInput: (e) => this.setState({ open: true, mode: "list", query: e.target.value, typed: true, active: 0, error: "" }),
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
					"aria-label": translate("Show options"),
					onMouseDown: (e) => e.preventDefault(),
					onClick: () => (open ? this.close() : (this.input?.focus(), this.open())),
				},
				icon(CHEVRON)
			),
		]);
	}

	renderSupport() {
		const { value, translate, missingText } = this.props;
		const { options, open, error, creating } = this.state;
		if (error) return h("div", { class: "wfs-support wfs-support--error", role: "alert" }, error);
		if (open || !value || !options || options.some((o) => o.name === value)) return null;
		return h("div", { class: "wfs-support wfs-support--warn" }, [
			`${missingText} `,
			h(
				"button",
				{ type: "button", class: "wfs-link", disabled: creating, onClick: () => this.create(value) },
				creating ? translate("Creating…") : translate("Create it")
			),
		]);
	}

	renderList() {
		const { value, translate, showDots, newLabel, emptyText } = this.props;
		const { active, options, query, typed, creating } = this.state;
		if (!options) return h("div", { class: "wfs-empty" }, translate("Loading…"));
		const { matches, canCreate } = this.visible();
		const showCreate = this.props.renderCreate || canCreate;
		return [
			h(
				"ul",
				{ class: "wfs-list", role: "listbox", id: `${this.props.id}-menu` },
				matches.map((o, i) =>
					h(
						"li",
						{
							key: o.name,
							role: "option",
							"aria-selected": o.name === value ? "true" : "false",
							class: `wfs-item${i === active ? " wfs-item--active" : ""}${o.name === value ? " wfs-item--selected" : ""}`,
							onMouseDown: (e) => e.preventDefault(),
							onMouseEnter: () => this.setState({ active: i }),
							onClick: () => this.select(o.name),
						},
						[showDots && dot(o.style), h("span", { class: "wfs-item-label" }, o.name), o.name === value && icon(CHECK)]
					)
				)
			),
			!matches.length && h("div", { class: "wfs-empty" }, emptyText),
			showCreate && h("div", { class: "wfs-divider" }),
			showCreate &&
				h(
					"button",
					{
						type: "button",
						class: `wfs-create-row${active === matches.length && canCreate ? " wfs-item--active" : ""}`,
						disabled: creating,
						onMouseDown: (e) => e.preventDefault(),
						onClick: () => this.create(canCreate ? query.trim() : ""),
					},
					[
						icon(PLUS),
						creating
							? h("span", null, translate("Creating…"))
							: canCreate && typed
							? h("span", null, [`${translate("Create")} ${this.props.recordLabel} `, h("strong", null, `“${query.trim()}”`)])
							: h("span", null, newLabel),
					]
				),
		];
	}

	render() {
		const { id, label, compact, renderCreate } = this.props;
		const { open, mode } = this.state;
		const entryClass = compact ? "wfs wfs--compact" : "bio-properties-panel-entry wfs";
		return h("div", { class: entryClass, "data-entry-id": id, ref: (el) => (this.root = el) }, [
			label && h("label", { for: id, class: "bio-properties-panel-label" }, label),
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
						? renderCreate({
								initialName: this.state.createName,
								onCreated: (record) => this.added(record),
								onCancel: () => this.setState({ mode: "list" }),
						  })
						: this.renderList()
				),
		]);
	}
}
