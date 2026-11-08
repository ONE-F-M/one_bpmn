import { h, Component } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { notifySummary } from "../shared/notifySummary";

// fieldname to label per DocType, fetched once per page
const labelsByDoctype = {};

export function loadLabels(doctype) {
	labelsByDoctype[doctype] ||= frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", { doctype })
		.then((fields) => Object.fromEntries((Array.isArray(fields) ? fields : []).map((f) => [f.fieldname, f.label])));
	return labelsByDoctype[doctype];
}

export const BADGE = h("svg", { width: 10, height: 10, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 3, "aria-hidden": "true" },
	h("path", { d: "M5 12l5 5L20 7" }));

// Class component, not hooks: a separate bundled Preact instance here crashes on useState.
export class NotifySummaryBox extends Component {
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
		const { values, taskActions, translate, onLaunch } = this.props;
		const summary = notifySummary(values, taskActions, this.state.labels);
		return h("div", {}, [
			h("button", { class: "spiffworkflow-properties-panel-button bpmn-notify-editor-btn", onClick: onLaunch, type: "button" }, [
				h("span", {}, translate("Launch Editor")),
				summary.configured && h("span", { class: "bpmn-notify-editor-badge", title: translate("Configured") }, BADGE),
			]),
			h("div", { class: "bio-properties-panel-description bpmn-mt-6" }, summary.line),
			h("div", { class: "bpmn-notify-summary" },
				summary.rows.map((r) => h("div", { class: "bpmn-notify-summary-row", key: r.k }, [
					h("span", { class: "bpmn-notify-summary-key" }, translate(r.k)),
					h("span", { class: `bpmn-notify-summary-value${r.warn ? " warn" : ""}`, title: r.v }, r.v),
				]))
			),
		]);
	}
}
