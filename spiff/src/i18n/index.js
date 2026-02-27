/**
 * i18n module for bpmn-js integration.
 * 
 * This module exports the custom translate function wrapped in
 * the format expected by bpmn-js additionalModules.
 */

import customTranslate from './customTranslate';

export default {
	translate: ['value', customTranslate]
};
