/**
 * An ad-hoc sub-process that an AI Agent Task names in aiToolsAdhoc is a tool catalogue:
 * compilation reads its shapes as the agent's tools, and no sequence flow enters it.
 */

import { is } from "bpmnlint-utils";

function isToolCatalogue(node) {
	if (!is(node, "bpmn:AdHocSubProcess")) {
		return false;
	}
	return node.$parent.flowElements.some((element) => element.get("spiffworkflow:aiToolsAdhoc") === node.id);
}

/** The given bpmnlint rule factory, skipping tool catalogues. */
export default function exemptToolCatalogues(ruleFactory) {
	return function () {
		const rule = ruleFactory();
		return {
			...rule,
			check(node, reporter) {
				if (!isToolCatalogue(node)) {
					rule.check(node, reporter);
				}
			},
		};
	};
}
