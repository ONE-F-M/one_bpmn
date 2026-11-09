/** Flags a tool shape in an agent's Tools box with no documentation, which is the description the model reads. */

import { inReferencedToolBox, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!inReferencedToolBox(node) || !isExecutable(node)) {
			return;
		}
		if ((node.documentation || []).some((doc) => String(doc.text || "").trim())) {
			return;
		}
		reporter.report(node.id, `Tool '${label(node)}' has no description; the model will see only its id`);
	}

	return { check };
}
