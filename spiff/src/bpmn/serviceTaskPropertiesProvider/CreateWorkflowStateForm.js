import { h, Component } from "preact";
import { frappePost } from "../shared/frappeResource";
import { WORKFLOW_STATE_STYLES, createWorkflowState } from "./workflowStateCreate";

// A class component because hooks crash in this bundled Preact; see CreateAgentConfigForm in ScriptTaskProps.js.
export class CreateWorkflowStateForm extends Component {
	constructor(props) {
		super(props);
		this.state = {
			open: false,
			saving: false,
			error: "",
			workflow_state_name: "",
			style: "Primary",
		};
	}

	async submitCreate() {
		const request = createWorkflowState(frappePost, this.state.workflow_state_name, this.state.style);
		if (!request) {
			this.setState({ error: this.props.translate("Name is required.") });
			return;
		}
		this.setState({ saving: true, error: "" });
		try {
			const createdName = await request;
			this.props.onCreated(createdName);
			this.setState({ open: false, saving: false, workflow_state_name: "", style: "Primary", error: "" });
		} catch (err) {
			// frappeRequest's own message leads with the URL; the server's readable text is in messages.
			this.setState({ saving: false, error: (err.messages && err.messages[0]) || err.message });
		}
	}

	render() {
		const { translate } = this.props;
		const { open, saving, error, workflow_state_name, style } = this.state;

		if (!open) {
			return h(
				"button",
				{ type: "button", class: "bpmn-add-row-btn", onClick: () => this.setState({ open: true }) },
				`+ ${translate("Create new Workflow State")}`
			);
		}

		return h("div", { class: "bpmn-config-area" }, [
			h("input", {
				type: "text",
				class: "bio-properties-panel-input",
				placeholder: translate('Name (e.g. "Pending Review")'),
				value: workflow_state_name,
				onInput: (e) => this.setState({ workflow_state_name: e.target.value }),
			}),
			h(
				"select",
				{
					class: "bio-properties-panel-input",
					value: style,
					onChange: (e) => this.setState({ style: e.target.value }),
				},
				WORKFLOW_STATE_STYLES.map((opt) =>
					h("option", { key: opt, value: opt }, translate(opt))
				)
			),
			error && h("div", { class: "bpmn-frappe-hint", style: "color:#c0392b" }, error),
			h("div", { style: "display:flex; gap:8px; margin-top:4px;" }, [
				h(
					"button",
					{
						type: "button",
						class: "bpmn-add-row-btn",
						disabled: saving,
						onClick: () => this.submitCreate(),
					},
					saving ? translate("Creating…") : translate("Save")
				),
				h(
					"button",
					{
						type: "button",
						class: "bpmn-add-row-btn",
						onClick: () => this.setState({ open: false, error: "" }),
					},
					translate("Cancel")
				),
			]),
		]);
	}
}
