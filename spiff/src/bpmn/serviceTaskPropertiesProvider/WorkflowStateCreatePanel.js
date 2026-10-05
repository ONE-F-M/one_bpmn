import { h, Component } from "preact";
import { frappePost } from "../shared/frappeResource";
import { WORKFLOW_STATE_STYLES, createWorkflowState } from "./workflowStateCreate";
import { CHECK, dot, icon } from "../shared/recordIcons";
import { serverMessage } from "@/utils/serverMessage";

// The "New workflow state" form inside the Next Workflow State menu; plain elements only, like its parent.
export class WorkflowStateCreatePanel extends Component {
	constructor(props) {
		super(props);
		this.state = { name: props.initialName || "", style: "Primary", saving: false, error: "" };
	}

	componentDidMount() {
		this.nameInput?.focus();
	}

	async submit() {
		const { translate, onCreated } = this.props;
		const request = createWorkflowState(frappePost, this.state.name, this.state.style);
		if (!request) {
			this.setState({ error: translate("Name is required.") });
			return;
		}
		this.setState({ saving: true, error: "" });
		try {
			onCreated({ name: await request, style: this.state.style });
		} catch (err) {
			this.setState({ saving: false, error: serverMessage(err) });
		}
	}

	render({ id, translate, onCancel }, { name, style, saving, error }) {
		return h("div", { class: "wfs-create" }, [
			h("div", { class: "wfs-create-title" }, translate("New workflow state")),
			h("label", { class: "wfs-create-label", for: `${id}-new-name` }, translate("Name")),
			h("input", {
				id: `${id}-new-name`,
				ref: (el) => (this.nameInput = el),
				class: `wfs-text${error ? " wfs-text--error" : ""}`,
				type: "text",
				placeholder: translate("e.g. Pending GRD Review"),
				value: name,
				onInput: (e) => this.setState({ name: e.target.value, error: "" }),
				onKeyDown: (e) => {
					if (e.key === "Enter") {
						e.preventDefault();
						this.submit();
					} else if (e.key === "Escape") {
						e.preventDefault();
						onCancel();
					}
				},
			}),
			h("div", { class: "wfs-create-label" }, translate("Colour")),
			h(
				"div",
				{ class: "wfs-chips", role: "radiogroup", "aria-label": translate("Colour") },
				WORKFLOW_STATE_STYLES.map((option) =>
					h(
						"button",
						{
							key: option,
							type: "button",
							role: "radio",
							"aria-checked": option === style ? "true" : "false",
							class: `wfs-chip${option === style ? " wfs-chip--on" : ""}`,
							onClick: () => this.setState({ style: option }),
						},
						[option === style ? icon(CHECK) : dot(option), translate(option)]
					)
				)
			),
			error && h("div", { class: "wfs-support wfs-support--error", role: "alert" }, error),
			h("div", { class: "wfs-actions" }, [
				h("button", { type: "button", class: "wfs-btn wfs-btn--text", onClick: onCancel }, translate("Cancel")),
				h(
					"button",
					{ type: "button", class: "wfs-btn wfs-btn--filled", disabled: saving, onClick: () => this.submit() },
					saving ? translate("Creating…") : translate("Create")
				),
			]),
		]);
	}
}
