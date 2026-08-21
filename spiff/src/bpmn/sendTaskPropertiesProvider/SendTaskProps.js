import { isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";
import { fixedDropdownStyle } from "../shared/dropdownPosition";

import { frappeGet } from "@/bpmn/shared/frappeResource";

// Channel emoji badges
const CHANNEL_ICONS = {
	Email: "📧",
	WhatsApp: "💬",
	"System Notification": "🔔",
	SMS: "📱",
	Slack: "🔗",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

// ---------------------------------------------------------------------------
// Notification Autocomplete Component
// ---------------------------------------------------------------------------
class NotificationAutocomplete extends Component {
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
		this.debounceTimer = null;
		this.handleDocumentClick = this.handleDocumentClick.bind(this);
		this.handleScroll = this.handleScroll.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.handleDocumentClick);
		// Fixed-position dropdown must follow its anchor when the panel scrolls
		document.addEventListener("scroll", this.handleScroll, true);
		window.addEventListener("resize", this.handleScroll);
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.handleDocumentClick);
		document.removeEventListener("scroll", this.handleScroll, true);
		window.removeEventListener("resize", this.handleScroll);
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
	}

	handleScroll() {
		if (this.state.isOpen) this.forceUpdate();
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
		const filters = [];
		if (txt) {
			filters.push(["name", "like", `%${txt}%`]);
		}
		frappeGet("/api/resource/Notification", {
			fields: '["name","subject","channel","document_type","enabled"]',
			filters: filters.length ? JSON.stringify(filters) : undefined,
			limit_page_length: 50,
			order_by: "modified desc",
		})
			.then((list) => {
				this.setState({ options: list || [], loading: false, isOpen: true });
			})
			.catch((err) => {
				console.error("[SendTask] Notification autocomplete error:", err);
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

		// Clear the model value while typing — only onSelect writes a valid name
		// (Review Comment #3: prevents partially-typed names from persisting)
		if (this.props.value) {
			this.props.onChange("");
		}
	}

	onSelect(val) {
		this.setState({ searchTxt: val, isOpen: false });
		this.props.onChange(val);
	}

	render() {
		const { id, label } = this.props;
		const { isOpen, options, loading, searchTxt } = this.state;

		return h(
			"div",
			{ class: "bio-properties-panel-entry", "data-entry-id": id, ref: (c) => (this.containerRef = c) },
			[
				h("div", { class: "bio-properties-panel-textfield bpmn-dropdown-wrap" }, [
					h("label", { for: id, class: "bio-properties-panel-label" }, label),
					h("input", {
						id: id,
						type: "text",
						class: "bio-properties-panel-input",
						value: searchTxt,
						ref: (c) => (this.inputRef = c),
						onInput: (e) => this.onInput(e),
						onFocus: () => this.onFocus(),
						autoComplete: "off",
						spellCheck: "false",
						placeholder: "Search notifications...",
					}),
					isOpen &&
						h(
							"ul",
							{
								class: "bpmn-dropdown-list",
								style: fixedDropdownStyle(this.inputRef),
							},
							[
								loading && h("li", { class: "bpmn-dropdown-loading" }, "Loading..."),
								!loading &&
									options.length === 0 &&
									h("li", { class: "bpmn-dropdown-loading" }, "No notifications found"),
								!loading &&
									options.map((opt) =>
										h(
											"li",
											{
												key: opt.name,
												class: "bpmn-dropdown-item",
												onMouseDown: (e) => {
													e.preventDefault();
													this.onSelect(opt.name);
												},
												onMouseEnter: (e) => (e.target.style.background = "#f3f4f6"),
												onMouseLeave: (e) => (e.target.style.background = "white"),
											},
											[
												h("div", { class: "bpmn-notif-item-title" }, [
													h("span", { class: "bpmn-notif-item-icon" }, CHANNEL_ICONS[opt.channel] || "📋"),
													opt.name,
												]),
												h("div", { class: "bpmn-notif-item-meta" }, [
													opt.channel,
													opt.document_type ? ` · ${opt.document_type}` : "",
													opt.enabled ? "" : " · Disabled",
												]),
											]
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
// Launch Notification Editor Button Component
// ---------------------------------------------------------------------------
function NotificationEditorButtonComponent(props) {
	const { element, id } = props;
	const translate = useService("translate");
	const bo = getBusinessObject(element);
	const eventBus = useService("eventBus");

	const handleClick = () => {
		eventBus.fire("spiff.notification.edit", {
			element,
			eventBus,
			notificationName: getAttr(bo, "notificationName"),
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"button",
			{
				class: "spiffworkflow-properties-panel-button",
				onClick: handleClick,
				type: "button",
			},
			translate("Configure Notification")
		)
	);
}


// ---------------------------------------------------------------------------
// Properties UI Provider
// ---------------------------------------------------------------------------
export function SendTaskProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);

	return [
		{
			id: "spiffworkflow-notificationName",
			element,
			component: NotificationNameComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-notificationEditorButton",
			element,
			component: NotificationEditorButtonComponent,
		},
	];
}


// ---------------------------------------------------------------------------
// Notification Name Autocomplete Component
// ---------------------------------------------------------------------------
function NotificationNameComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "notificationName");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:notificationName": val || undefined,
		});
	};

	return h(NotificationAutocomplete, {
		id,
		label: translate("Linked Notification"),
		value,
		onChange: handleChange,
	});
}
