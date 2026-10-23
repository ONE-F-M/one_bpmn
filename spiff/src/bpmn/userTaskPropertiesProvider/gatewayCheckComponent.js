import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { checkGateway } from "./gatewayCheck";

// Read-only "Gateway check" entry shown under Task Actions. It reads the
// diagram and writes nothing, so it can never block a deploy.

// The exclusive gateway directly after the task, with one condition body per
// outgoing branch. null when no exclusive gateway follows the task.
function readGateway(element) {
	const bo = getBusinessObject(element);
	const gateway = (bo.outgoing || [])
		.map((flow) => flow.targetRef)
		.find((target) => target && target.$type === "bpmn:ExclusiveGateway");
	if (!gateway) return null;
	const bodies = (gateway.outgoing || []).map(
		(flow) => (flow.conditionExpression && flow.conditionExpression.body) || ""
	);
	return { gateway, bodies };
}

function signatureOf(element) {
	const found = readGateway(element);
	return found ? JSON.stringify([found.gateway.id, found.gateway.name, found.bodies]) : "";
}

// The panel only re-renders when the selected element changes, and a branch
// condition lives on another element. One listener per event bus compares the
// gateway signature of every task the panel has shown and asks the panel to
// refresh the ones that moved.
const watched = new WeakMap();

function watch(eventBus, element) {
	let elements = watched.get(eventBus);
	if (!elements) {
		elements = new Map();
		watched.set(eventBus, elements);
		eventBus.on("commandStack.changed", () => {
			elements.forEach((signature, el) => {
				const now = signatureOf(el);
				if (now === signature) return;
				elements.set(el, now);
				eventBus.fire("elements.changed", { elements: [el] });
			});
		});
	}
	elements.set(element, signatureOf(element));
}

// parseActions(raw) turns the stored taskActions value into [{action}, ...].
export function makeGatewayCheckComponent(parseActions) {
	return function GatewayCheckComponent(props) {
		const { element, id } = props;
		const translate = useService("translate");
		const eventBus  = useService("eventBus");
		const bo        = getBusinessObject(element);

		watch(eventBus, element);

		const found = readGateway(element);
		if (!found) return null;

		const actionNames = parseActions(bo.get("spiffworkflow:taskActions") || "")
			.map((row) => row.action);
		const rows = checkGateway(actionNames, found.bodies, translate);

		return h("div", { class: "bio-properties-panel-entry", "data-entry-id": id }, [
			h("label", { class: "bio-properties-panel-label" },
				translate('Gateway "{name}"', { name: found.gateway.name || found.gateway.id })),
			h("div", { class: "bpmn-link-list" },
				rows.map((row, idx) =>
					h("div", { key: `gateway-check-${idx}`, class: `bpmn-link bpmn-link-${row.state}` }, [
						h("i", {}),
						h("span", {}, row.text),
					])
				)
			),
		]);
	};
}
