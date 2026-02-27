/**
 * Custom translate function for bpmn-js i18n support.
 * 
 * This module provides translation capabilities for the BPMN modeler.
 * Add translations to the 'translations' object below.
 * 
 * Usage: Template strings with placeholders like "Append {element}" 
 * will have {element} replaced with the actual value.
 */

// Translation dictionary - add more translations as needed
const translations = {
	// Palette entries
	"Append": "Append",
	"Create Start Event": "Create Start Event",
	"Create End Event": "Create End Event",
	"Create Intermediate/Boundary Event": "Create Intermediate/Boundary Event",
	"Create Gateway": "Create Gateway",
	"Create Task": "Create Task",
	"Create DataObjectReference": "Create Data Object Reference",
	"Create DataStoreReference": "Create Data Store Reference",
	"Create Pool/Participant": "Create Pool/Participant",
	"Create Group": "Create Group",
	"Create expanded SubProcess": "Create expanded SubProcess",
	"Activate the hand tool": "Activate the hand tool",
	"Activate the lasso tool": "Activate the lasso tool",
	"Activate the create/remove space tool": "Activate the create/remove space tool",
	"Activate the global connect tool": "Activate the global connect tool",
	
	// Context pad entries
	"Append {type}": "Append {type}",
	"Connect using Association": "Connect using Association",
	"Connect using Sequence/MessageFlow or Association": "Connect using Sequence/MessageFlow or Association",
	"Connect using DataInputAssociation": "Connect using DataInputAssociation",
	"Change type": "Change type",
	"Remove": "Remove",
	"Delete": "Delete",
	
	// Element types
	"End Event": "End Event",
	"Gateway": "Gateway",
	"Intermediate Throw Event": "Intermediate Throw Event",
	"Task": "Task",
	"TextAnnotation": "Text Annotation",
	
	// Replace menu
	"Replace with": "Replace with",
	"None End Event": "None End Event",
	"Message End Event": "Message End Event",
	"Escalation End Event": "Escalation End Event",
	"Error End Event": "Error End Event",
	"Cancel End Event": "Cancel End Event",
	"Compensation End Event": "Compensation End Event",
	"Signal End Event": "Signal End Event",
	"Terminate End Event": "Terminate End Event",
	
	// Modeling actions
	"flow": "flow",
	"Element": "Element",
	"Elements": "Elements",
};

/**
 * Translate a template string with optional replacements.
 * 
 * @param {string} template - The template string to translate
 * @param {Object} replacements - Optional object with replacement values
 * @returns {string} The translated (and interpolated) string
 */
export default function customTranslate(template, replacements) {
	replacements = replacements || {};
	
	// Translate the template
	let translation = translations[template] || template;
	
	// Replace placeholders with actual values
	return translation.replace(/{([^}]+)}/g, function(_, key) {
		return replacements[key] || '{' + key + '}';
	});
}
