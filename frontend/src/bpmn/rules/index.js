/**
 * Custom rules module for bpmn-js integration.
 * 
 * Export this module to add to additionalModules in the modeler.
 */

import CustomRules from './CustomRules';

export default {
	__init__: ['customRules'],
	customRules: ['type', CustomRules]
};
