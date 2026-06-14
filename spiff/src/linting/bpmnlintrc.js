/**
 * Packed bpmnlint configuration for bpmn-js-bpmnlint.
 *
 * This hand-rolled config object replaces the CLI `bpmnlint-pack-config` step,
 * which fails under Node 18 due to ESM/CJS interop issues in min-dash.
 *
 * Shape: { config: { rules: { ... } }, resolver: { resolveRule(pkg, name) } }
 *
 * To add or remove rules:
 *   1. Import the rule factory from 'bpmnlint/rules/<rule-name>'
 *   2. Add/remove it from `ruleMapping`
 *   3. Update `config.rules` with the desired severity ('error' | 'warn' | 'off')
 */

// --- Rule imports ---
import adHocSubProcess from "bpmnlint/rules/ad-hoc-sub-process";
import conditionalEvent from "bpmnlint/rules/conditional-event";
import conditionalFlows from "bpmnlint/rules/conditional-flows";
import endEventRequired from "bpmnlint/rules/end-event-required";
import eventBasedGateway from "bpmnlint/rules/event-based-gateway";
import eventSubProcessTypedStartEvent from "bpmnlint/rules/event-sub-process-typed-start-event";
import fakeJoin from "bpmnlint/rules/fake-join";
import labelRequired from "bpmnlint/rules/label-required";
import linkEvent from "bpmnlint/rules/link-event";
import noBpmndi from "bpmnlint/rules/no-bpmndi";
import noComplexGateway from "bpmnlint/rules/no-complex-gateway";
import noDisconnected from "bpmnlint/rules/no-disconnected";
import noDuplicateSequenceFlows from "bpmnlint/rules/no-duplicate-sequence-flows";
import noGatewayJoinFork from "bpmnlint/rules/no-gateway-join-fork";
import noImplicitEnd from "bpmnlint/rules/no-implicit-end";
import noImplicitSplit from "bpmnlint/rules/no-implicit-split";
import noImplicitStart from "bpmnlint/rules/no-implicit-start";
import noInclusiveGateway from "bpmnlint/rules/no-inclusive-gateway";
import noOverlappingElements from "bpmnlint/rules/no-overlapping-elements";
import singleBlankStartEvent from "bpmnlint/rules/single-blank-start-event";
import singleEventDefinition from "bpmnlint/rules/single-event-definition";
import startEventRequired from "bpmnlint/rules/start-event-required";
import subProcessBlankStartEvent from "bpmnlint/rules/sub-process-blank-start-event";
import superfluousGateway from "bpmnlint/rules/superfluous-gateway";
import superfluousTermination from "bpmnlint/rules/superfluous-termination";

// --- Custom OneFM rules ---
import noProhibitedShapes from "@/linting/rules/no-prohibited-shapes.js";

/**
 * Map rule names → rule factory functions.
 * The resolver uses this to look up rules by name at runtime.
 */
const ruleMapping = {
	"bpmnlint/ad-hoc-sub-process": adHocSubProcess,
	"bpmnlint/conditional-event": conditionalEvent,
	"bpmnlint/conditional-flows": conditionalFlows,
	"bpmnlint/end-event-required": endEventRequired,
	"bpmnlint/event-based-gateway": eventBasedGateway,
	"bpmnlint/event-sub-process-typed-start-event": eventSubProcessTypedStartEvent,
	"bpmnlint/fake-join": fakeJoin,
	"bpmnlint/label-required": labelRequired,
	"bpmnlint/link-event": linkEvent,
	"bpmnlint/no-bpmndi": noBpmndi,
	"bpmnlint/no-complex-gateway": noComplexGateway,
	"bpmnlint/no-disconnected": noDisconnected,
	"bpmnlint/no-duplicate-sequence-flows": noDuplicateSequenceFlows,
	"bpmnlint/no-gateway-join-fork": noGatewayJoinFork,
	"bpmnlint/no-implicit-end": noImplicitEnd,
	"bpmnlint/no-implicit-split": noImplicitSplit,
	"bpmnlint/no-implicit-start": noImplicitStart,
	"bpmnlint/no-inclusive-gateway": noInclusiveGateway,
	"bpmnlint/no-overlapping-elements": noOverlappingElements,
	"bpmnlint/single-blank-start-event": singleBlankStartEvent,
	"bpmnlint/single-event-definition": singleEventDefinition,
	"bpmnlint/start-event-required": startEventRequired,
	"bpmnlint/sub-process-blank-start-event": subProcessBlankStartEvent,
	"bpmnlint/superfluous-gateway": superfluousGateway,
	"bpmnlint/superfluous-termination": superfluousTermination,

	// Custom OneFM rules
	"custom/no-prohibited-shapes": noProhibitedShapes,
};

const config = {
	rules: {
		// Structural errors
		"bpmnlint/start-event-required": "error",
		"bpmnlint/end-event-required": "error",
		"bpmnlint/no-disconnected": "error",
		"bpmnlint/single-blank-start-event": "error",
		"bpmnlint/no-bpmndi": "error",
		"bpmnlint/event-sub-process-typed-start-event": "error",
		"bpmnlint/sub-process-blank-start-event": "error",

		// Gateway & flow correctness
		"bpmnlint/conditional-flows": "warn",
		"bpmnlint/event-based-gateway": "warn",
		"bpmnlint/no-complex-gateway": "warn",
		"bpmnlint/no-gateway-join-fork": "warn",
		"bpmnlint/no-inclusive-gateway": "warn",
		"bpmnlint/superfluous-gateway": "warn",

		// Flow & split/join patterns
		"bpmnlint/no-implicit-split": "warn",
		"bpmnlint/no-implicit-start": "warn",
		"bpmnlint/no-implicit-end": "warn",
		"bpmnlint/fake-join": "warn",
		"bpmnlint/no-duplicate-sequence-flows": "warn",

		// Labelling & readability
		"bpmnlint/label-required": "warn",
		"bpmnlint/no-overlapping-elements": "warn",

		// Event correctness
		"bpmnlint/ad-hoc-sub-process": "warn",
		"bpmnlint/conditional-event": "warn",
		"bpmnlint/link-event": "warn",
		"bpmnlint/single-event-definition": "warn",
		"bpmnlint/superfluous-termination": "warn",

		// OneFM custom rules — prohibited shapes (executable processes only)
		"custom/no-prohibited-shapes": "error",
	},
};

const resolver = {
	resolveRule(pkg, name) {
		// bpmnlint resolves standard rules as resolveRule('bpmnlint', 'rule-name').
		// For custom rules, bpmnlint's parseRuleName converts "custom/rule-name"
		// to pkg = "bpmnlint-plugin-custom", so we must also try the un-prefixed
		// package name when looking up in ruleMapping.
		const key = pkg + "/" + name;
		if (ruleMapping[key]) return ruleMapping[key];

		// Strip "bpmnlint-plugin-" prefix to match our shorthand keys
		if (pkg.startsWith("bpmnlint-plugin-")) {
			const shortPkg = pkg.slice("bpmnlint-plugin-".length);
			const shortKey = shortPkg + "/" + name;
			if (ruleMapping[shortKey]) return ruleMapping[shortKey];
		}

		return null;
	},
};

export default { config, resolver };
