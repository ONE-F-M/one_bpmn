import { h, Component } from "preact";
import { ListGroup } from "@bpmn-io/properties-panel";
import { frappePost } from "../shared/frappeResource";
import { serverMessage } from "@/utils/serverMessage";
import { createBpmnSignalMaster } from "./signalPick";
import { SIGNALS } from "./signalRecords";

// The name box of a new signal row: Enter or leaving the box creates the record. Plain elements only, like the pickers.
class SignalNameInput extends Component {
	constructor(props) {
		super(props);
		this.state = { saving: false, error: "" };
	}

	componentDidMount() {
		this.input?.focus();
	}

	async commit() {
		const name = this.input.value.trim();
		if (!name || this.state.saving) return;
		this.setState({ saving: true, error: "" });
		try {
			await this.props.onCreate(name);
		} catch (err) {
			this.setState({ saving: false, error: serverMessage(err) });
		}
	}

	render({ translate, onCancel }, { saving, error }) {
		return h("div", { class: "bio-properties-panel-entry" }, [
			h("input", {
				ref: (el) => (this.input = el),
				class: "bio-properties-panel-input",
				type: "text",
				disabled: saving,
				placeholder: translate("Signal name"),
				onKeyDown: (e) => {
					if (e.key === "Enter") {
						e.preventDefault();
						this.commit();
					} else if (e.key === "Escape") {
						onCancel();
					}
				},
				onBlur: () => this.commit(),
			}),
			error && h("div", { class: "bio-properties-panel-error" }, error),
		]);
	}
}

function SignalNameText({ name }) {
	return h("div", { class: "bio-properties-panel-entry" }, h("input", { class: "bio-properties-panel-input", type: "text", readOnly: true, value: name }));
}

// The process-level Signals list, backed by BPMN Signal Master: it lists the records, + creates one. Deleting is left to the BPMN Signal Master list, so rows carry no remove control.
export function signalListGroup({ element, translate, drafts, loadError, refresh }) {
	const records = SIGNALS.get() || [];

	const items = records.map((record, idx) => {
		const id = `signal-${idx}`;
		return {
			id,
			label: record.name,
			entries: [{ id: `${id}-name`, component: SignalNameText, name: record.name }],
		};
	});

	drafts.forEach((draft) => {
		items.push({
			id: draft,
			label: translate("New signal"),
			entries: [
				{
					id: `${draft}-name`,
					component: SignalNameInput,
					translate,
					onCancel: () => {
						drafts.delete(draft);
						refresh();
					},
					onCreate: async (name) => {
						SIGNALS.add({ name: await createBpmnSignalMaster(frappePost, name) });
						drafts.delete(draft);
						refresh();
					},
				},
			],
		});
	});

	if (loadError) items.push({ id: "signals-load-error", label: loadError, entries: [] });

	return {
		id: "signals",
		element,
		label: translate("Signals"),
		component: ListGroup,
		items,
		add: (event) => {
			event.stopPropagation();
			drafts.add(`signal-new-${drafts.size}-${Date.now()}`);
			refresh();
		},
	};
}
