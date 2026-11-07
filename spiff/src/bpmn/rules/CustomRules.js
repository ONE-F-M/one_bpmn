/**
 * Custom BPMN modeling rules.
 * 
 * This module extends the default BPMN rules to add custom constraints
 * for your specific modeling requirements.
 * 
 * Rules can prevent certain modeling actions, such as:
 * - Creating connections between specific element types
 * - Placing elements in certain containers
 * - Moving/attaching elements
 */

import RuleProvider from 'diagram-js/lib/features/rules/RuleProvider';
import inherits from 'inherits-browser';

/**
 * CustomRules class that extends RuleProvider.
 * Add your custom rules in the init() method.
 */
export default function CustomRules(eventBus) {
	RuleProvider.call(this, eventBus);
}

inherits(CustomRules, RuleProvider);

CustomRules.$inject = ['eventBus'];

CustomRules.prototype.init = function() {
	
	/**
	 * Example: Prevent connecting End Events directly to Start Events
	 */
	this.addRule('connection.create', function(context) {
		const source = context.source;
		const target = context.target;
		
		// Get business objects
		const sourceBo = source.businessObject;
		const targetBo = target.businessObject;
		
		// Prevent End Event -> Start Event connections
		if (sourceBo.$type === 'bpmn:EndEvent' && targetBo.$type === 'bpmn:StartEvent') {
			return false;
		}
		
		// Allow all other connections (return undefined to use default rules)
		return undefined;
	});
	
	/**
	 * Example: Limit the number of outgoing sequence flows from a task
	 * Uncomment to enable this rule
	 */
	/*
	this.addRule('connection.create', 1500, function(context) {
		const source = context.source;
		const sourceBo = source.businessObject;
		
		// Only apply to tasks
		if (sourceBo.$type !== 'bpmn:Task') {
			return undefined;
		}
		
		// Count existing outgoing flows
		const outgoing = source.outgoing || [];
		
		// Limit to 3 outgoing connections from a single task
		if (outgoing.length >= 3) {
			return false;
		}
		
		return undefined;
	});
	*/
	
	/**
	 * Example: Prevent dropping elements outside the process/pool
	 * Uncomment to enable this rule
	 */
	/*
	this.addRule('shape.create', function(context) {
		const parent = context.parent;
		const shape = context.shape;
		
		// Ensure elements are placed in a process or participant
		if (!parent || parent.type === 'bpmn:Collaboration') {
			const shapeBo = shape.businessObject;
			
			// Allow only participants at root level
			if (shapeBo.$type !== 'bpmn:Participant') {
				return false;
			}
		}
		
		return undefined;
	});
	*/
};
