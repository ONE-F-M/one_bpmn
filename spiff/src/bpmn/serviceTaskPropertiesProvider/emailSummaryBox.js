import { h, Component } from "preact";
import { emailSummary } from "../shared/emailNotification";
import { BADGE, loadLabels } from "../userTaskPropertiesProvider/notifySummaryBox";

// Class component, not hooks: a separate bundled Preact instance here crashes on useState.
export class EmailSummaryBox extends Component {
	constructor(props) {
		super(props);
		this.state = { labels: {} };
	}

	componentDidMount() {
		this.fetchLabels();
	}

	componentDidUpdate(prev) {
		if (prev.doctype !== this.props.doctype) this.fetchLabels();
	}

	fetchLabels() {
		const { doctype } = this.props;
		if (!doctype) return;
		loadLabels(doctype).then((labels) => {
			if (this.props.doctype === doctype) this.setState({ labels });
		});
	}

	render() {
		const { values, translate, onLaunch } = this.props;
		const summary = emailSummary(values, this.state.labels);
		return h("div", {}, [
			h("button", { class: "spiffworkflow-properties-panel-button bpmn-notify-editor-btn", onClick: onLaunch, type: "button" }, [
				h("span", {}, translate("Launch Editor")),
				summary.configured && h("span", { class: "bpmn-notify-editor-badge", title: translate("Configured") }, BADGE),
			]),
			h("div", { class: "bio-properties-panel-description bpmn-mt-6" },
				translate("Values below change only when you press Save in the editor.")),
			h("div", { class: "bpmn-notify-summary" },
				summary.rows.map((r) => h("div", { class: "bpmn-notify-summary-row", key: r.k }, [
					h("span", { class: "bpmn-notify-summary-key" }, translate(r.k)),
					h("span", { class: `bpmn-notify-summary-value${r.warn ? " warn" : ""}`, title: r.v }, r.v),
				]))
			),
		]);
	}
}
