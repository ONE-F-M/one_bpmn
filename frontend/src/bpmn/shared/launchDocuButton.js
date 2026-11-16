import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { HeaderButton } from "@bpmn-io/properties-panel";

/**
 * launchDocuButton — shared factory for the "Launch Docu" properties-panel button.
 *
 * Docu is the AI DocType builder. Any shape with a doctype-selection field
 * (Start Event → triggerDoctype, User Task → targetDoctype, Service Task →
 * serviceTargetDoctype, ...) gets one of these buttons next to that field.
 *
 * `attr` is the spiffworkflow:* attribute (WITHOUT the prefix) that both holds
 * the currently selected DocType and receives the applied DocType name when the
 * Docu panel finishes.
 *
 * Mechanism mirrors ScriptTaskProps.LaunchEditorButton:
 *   fire  "launch-docu-editor"  { element, doctype, attr, eventBus }
 *   once  "docu.doctype.update" { doctype }  → write back to spiffworkflow:<attr>
 *
 * Returns a Preact component suitable for a properties-panel entry `component`.
 */
export function makeLaunchDocuButton(attr, label = "Launch Docu") {
	return function LaunchDocuButton(props) {
		const { element } = props;
		const eventBus = useService("eventBus");
		const modeling = useService("modeling");
		const translate = useService("translate");
		const bo = getBusinessObject(element);

		return HeaderButton({
			className: "spiffworkflow-properties-panel-button docu-launch-btn",
			onClick: () => {
				const doctype = bo.get(`spiffworkflow:${attr}`) || "";
				eventBus.fire("launch-docu-editor", { element, doctype, attr, eventBus });

				// One-shot listener: write the applied DocType name back onto the shape.
				eventBus.once("docu.doctype.update", (event) => {
					const name = (event && event.doctype) || "";
					modeling.updateModdleProperties(element, bo, {
						[`spiffworkflow:${attr}`]: name || undefined,
					});
				});
			},
			children: translate(label),
		});
	};
}
