/**
 * Packed bpmnlint configuration for bpmn-js-bpmnlint.
 *
 * This hand-rolled config object replaces the CLI `bpmnlint-pack-config` step,
 * which fails under Node 18 due to ESM/CJS interop issues in min-dash.
 *
 * Shape: { config: { rules: { ... } }, resolver: { resolveRule(pkg, name) } }
 *
 * To add or remove rules:
 *   1. Import the rule factory from 'bpmnlint/rules/\<rule-name\>'
 *   2. Add/remove it from `ruleMapping`
 *   3. Update `config.rules` with the desired severity ('error' | 'warn' | 'off')
 */

import labelRequired from 'bpmnlint/rules/label-required';
import startEventRequired from 'bpmnlint/rules/start-event-required';
import endEventRequired from 'bpmnlint/rules/end-event-required';
import noDisconnected from 'bpmnlint/rules/no-disconnected';
import noImplicitSplit from 'bpmnlint/rules/no-implicit-split';
import fakeJoin from 'bpmnlint/rules/fake-join';
import singleBlankStartEvent from 'bpmnlint/rules/single-blank-start-event';
import noDuplicateSequenceFlows from 'bpmnlint/rules/no-duplicate-sequence-flows';

/**
 * Map rule names → rule factory functions.
 * The resolver uses this to look up rules by name at runtime.
 */
const ruleMapping = {
	'bpmnlint/label-required': labelRequired,
	'bpmnlint/start-event-required': startEventRequired,
	'bpmnlint/end-event-required': endEventRequired,
	'bpmnlint/no-disconnected': noDisconnected,
	'bpmnlint/no-implicit-split': noImplicitSplit,
	'bpmnlint/fake-join': fakeJoin,
	'bpmnlint/single-blank-start-event': singleBlankStartEvent,
	'bpmnlint/no-duplicate-sequence-flows': noDuplicateSequenceFlows,
};

const config = {
	rules: {
		'bpmnlint/label-required': 'warn',
		'bpmnlint/start-event-required': 'error',
		'bpmnlint/end-event-required': 'error',
		'bpmnlint/no-disconnected': 'error',
		'bpmnlint/no-implicit-split': 'warn',
		'bpmnlint/fake-join': 'warn',
		'bpmnlint/single-blank-start-event': 'error',
		'bpmnlint/no-duplicate-sequence-flows': 'warn',
	},
};

const resolver = {
	resolveRule(pkg, name) {
		// bpmnlint resolves rules as resolveRule('bpmnlint', 'rule-name')
		// Our mapping uses the combined key 'bpmnlint/rule-name'
		const key = pkg + '/' + name;
		return ruleMapping[key] || null;
	},
};

export default { config, resolver };
