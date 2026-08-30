import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";
import { HeaderButton } from "@bpmn-io/properties-panel";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet, frappePost } from "../shared/frappeResource";

function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

export function ScriptTaskProps(props) {
	const { element } = props;
	return [
		{ id: "spiffworkflow-serverScript", element, component: ServerScriptComponent },
		{ id: "spiffworkflow-launchEditor", element, component: LaunchEditorButton },
		{ id: "spiffworkflow-aiAgentConfig", element, component: AiAgentConfigOverrideComponent },
	];
}

function ServerScriptComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const currentValue = getAttr(bo, "serverScript");

	const handleSelect = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:serverScript": value || undefined,
		});
		// Also set bpmn:script so linting doesn't complain about empty script
		modeling.updateProperties(element, {
			script: value || undefined,
		});
	};

	// Fetch API-type Server Scripts from Frappe
	const fetchServerScripts = (txt) => {
		const params = {
			fields: '["name"]',
			filters: JSON.stringify([
				["script_type", "=", "API"],
				...(txt ? [["name", "like", `%${txt}%`]] : []),
			]),
			limit_page_length: 50,
			order_by: "name asc",
		};
		return frappeGet("/api/resource/Server Script", params);
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h("label", { class: "bio-properties-panel-label" }, translate("Server Script")),
			h(FrappeAutocomplete, {
				value: currentValue,
				placeholder: translate("Select a Frappe Server Script (API type)…"),
				fetchApi: fetchServerScripts,
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: handleSelect,
			}),
		])
	);
}

// Optional: lets a script's own internal LLM call pick its AI Agent Configuration.
function fetchAgentConfigs(txt) {
	return frappeGet("/api/resource/AI Agent Configuration", {
		fields: '["name","agent_id"]',
		filters: JSON.stringify([
			["enabled", "=", 1],
			...(txt ? [["name", "like", `%${txt}%`]] : []),
		]),
		limit_page_length: 50,
		order_by: "name asc",
	});
}

function fetchProviders(txt) {
	return frappeGet("/api/resource/AI Provider", {
		fields: '["name"]',
		filters: JSON.stringify([
			["enabled", "=", 1],
			...(txt ? [["name", "like", `%${txt}%`]] : []),
		]),
		limit_page_length: 50,
		order_by: "name asc",
	});
}

function fetchAiModels(txt) {
	return frappeGet("/api/resource/AI Model", {
		fields: '["name"]',
		filters: JSON.stringify(txt ? [["name", "like", `%${txt}%`]] : []),
		limit_page_length: 50,
		order_by: "name asc",
	});
}

// Class component, not hooks — a separate bundled Preact instance here
// crashes on `useState` (see vite.config.js's preact/hooks dedupe note).
class CreateAgentConfigForm extends Component {
	constructor(props) {
		super(props);
		this.state = {
			open: false,
			saving: false,
			error: "",
			agent_name: "",
			system_prompt: "",
			ai_provider: "",
			ai_model: "",
		};
	}

	// Reuses the same create_agent_configuration endpoint the AI Agent Task modal uses.
	submitCreate() {
		const name = (this.state.agent_name || "").trim();
		if (!name) {
			this.setState({ error: this.props.translate("Name is required.") });
			return;
		}
		this.setState({ saving: true, error: "" });
		frappePost("/api/method/one_bpmn.agents.agent_config_resolver.create_agent_configuration", {
			payload: JSON.stringify({
				agent_name: name,
				agent_type: "Background",
				agent_framework: "Direct API",
				system_prompt: this.state.system_prompt,
				ai_provider: this.state.ai_provider || undefined,
				ai_model: this.state.ai_model || undefined,
			}),
		})
			.then((res) => {
				const createdName = (res && res.name) || (res && res.message && res.message.name);
				if (!createdName) throw new Error("No name returned");
				this.props.onCreated(createdName);
				this.setState({
					open: false,
					saving: false,
					agent_name: "",
					system_prompt: "",
					ai_provider: "",
					ai_model: "",
				});
			})
			.catch((err) => {
				this.setState({
					saving: false,
					error: (err && err.message) || this.props.translate("Could not create the configuration."),
				});
			});
	}

	render() {
		const { translate } = this.props;
		const { open, saving, error, agent_name, system_prompt, ai_provider, ai_model } = this.state;

		if (!open) {
			return h(
				"button",
				{ type: "button", class: "bpmn-add-row-btn", onClick: () => this.setState({ open: true }) },
				`+ ${translate("Create new configuration")}`
			);
		}

		return h("div", { class: "bpmn-config-area" }, [
			h("input", {
				type: "text",
				class: "bio-properties-panel-input",
				placeholder: translate('Name (e.g. "Ticket Summariser")'),
				value: agent_name,
				onInput: (e) => this.setState({ agent_name: e.target.value }),
			}),
			h("textarea", {
				class: "bpmn-frappe-textarea",
				rows: 3,
				placeholder: translate("System prompt (optional)"),
				value: system_prompt,
				onInput: (e) => this.setState({ system_prompt: e.target.value }),
			}),
			h(FrappeAutocomplete, {
				label: translate("AI Provider"),
				value: ai_provider,
				placeholder: translate("Optional…"),
				fetchApi: fetchProviders,
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: (v) => this.setState({ ai_provider: v }),
			}),
			h(FrappeAutocomplete, {
				label: translate("AI Model"),
				value: ai_model,
				placeholder: translate("Optional…"),
				fetchApi: fetchAiModels,
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: (v) => this.setState({ ai_model: v }),
			}),
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
					saving ? translate("Creating…") : translate("Create")
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

function AiAgentConfigOverrideComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const currentValue = getAttr(bo, "aiAgentConfig");

	const handleSelect = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:aiAgentConfig": value || undefined,
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h(
				"label",
				{
					class: "bio-properties-panel-label",
					title: translate(
						"Optional. If this script makes its own internal LLM call, it names which AI Agent Configuration to use here (falls back to a default baked into the script when unset)."
					),
				},
				translate("Internal AI Agent Configuration")
			),
			h(FrappeAutocomplete, {
				value: currentValue,
				placeholder: translate("Uses the script's default…"),
				fetchApi: fetchAgentConfigs,
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: handleSelect,
			}),
			h(CreateAgentConfigForm, { translate, onCreated: handleSelect }),
		])
	);
}

function LaunchEditorButton(props) {
	const { element } = props;
	const eventBus  = useService("eventBus");
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return HeaderButton({
		className: "spiffworkflow-properties-panel-button",
		onClick: () => {
			const currentScript = getAttr(bo, "serverScript") || bo.get("script") || "";
			eventBus.fire("spiff.script.edit", {
				element,
				scriptType: "bpmn:script",
				script: currentScript,
				eventBus,
			});

			// Listen for the dialog response
			eventBus.once("spiff.script.update", (event) => {
				const scriptName = event.script || "";
				// Update spiffworkflow:serverScript (engine reads this)
				modeling.updateModdleProperties(element, bo, {
					"spiffworkflow:serverScript": scriptName || undefined,
				});
				// Also set bpmn:script to satisfy linting
				modeling.updateProperties(element, {
					script: scriptName || undefined,
				});
			});
		},
		children: translate("Launch Logix"),
	});
}
