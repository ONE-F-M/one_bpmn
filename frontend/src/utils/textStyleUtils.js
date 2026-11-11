/**
 * Text Style Utilities for BPMN Elements
 * 
 * These utilities read and write text style properties to BPMN extension elements.
 * Styles are stored in a custom namespace and persist with the BPMN XML.
 */

// Default text style values
export const DEFAULT_TEXT_STYLE = {
	fontWeight: "normal",      // "normal" | "bold"
	fontStyle: "normal",       // "normal" | "italic"
	textDecoration: "none",    // "none" | "underline"
	fontSize: 12,              // number in pixels
	textColor: "#1f2937",      // hex color
	fontFamily: "Inter",       // font family name
};

/**
 * Get text style from a BPMN element
 * Reads from element's businessObject extensionElements
 * 
 * @param {Object} element - BPMN element (shape)
 * @returns {Object} Text style object
 */
export function getTextStyle(element) {
	if (!element || !element.businessObject) {
		return { ...DEFAULT_TEXT_STYLE };
	}

	const bo = element.businessObject;
	
	// Check for custom text style properties stored directly on businessObject
	// This is a simpler approach than full extension elements
	const style = {
		fontWeight: bo.get("custom:fontWeight") || DEFAULT_TEXT_STYLE.fontWeight,
		fontStyle: bo.get("custom:fontStyle") || DEFAULT_TEXT_STYLE.fontStyle,
		textDecoration: bo.get("custom:textDecoration") || DEFAULT_TEXT_STYLE.textDecoration,
		fontSize: parseInt(bo.get("custom:fontSize")) || DEFAULT_TEXT_STYLE.fontSize,
		textColor: bo.get("custom:textColor") || DEFAULT_TEXT_STYLE.textColor,
		fontFamily: bo.get("custom:fontFamily") || DEFAULT_TEXT_STYLE.fontFamily,
	};

	return style;
}

/**
 * Check if element has any custom text style
 * 
 * @param {Object} element - BPMN element
 * @returns {boolean} True if element has custom styling
 */
export function hasCustomTextStyle(element) {
	if (!element || !element.businessObject) {
		return false;
	}

	const bo = element.businessObject;
	return !!(
		bo.get("custom:fontWeight") ||
		bo.get("custom:fontStyle") ||
		bo.get("custom:textDecoration") ||
		bo.get("custom:fontSize") ||
		bo.get("custom:textColor") ||
		bo.get("custom:fontFamily")
	);
}

/**
 * Set text style on a BPMN element using the modeling API
 * 
 * @param {Object} modeling - bpmn-js modeling service
 * @param {Object} element - BPMN element
 * @param {Object} style - Partial style object to apply
 */
export function setTextStyle(modeling, element, style) {
	if (!modeling || !element) {
		console.error("Missing modeling or element for setTextStyle");
		return;
	}

	const properties = {};
	
	if (style.fontWeight !== undefined) {
		properties["custom:fontWeight"] = style.fontWeight;
	}
	if (style.fontStyle !== undefined) {
		properties["custom:fontStyle"] = style.fontStyle;
	}
	if (style.textDecoration !== undefined) {
		properties["custom:textDecoration"] = style.textDecoration;
	}
	if (style.fontSize !== undefined) {
		properties["custom:fontSize"] = String(style.fontSize);
	}
	if (style.textColor !== undefined) {
		properties["custom:textColor"] = style.textColor;
	}
	if (style.fontFamily !== undefined) {
		properties["custom:fontFamily"] = style.fontFamily;
	}

	// Use modeling.updateProperties to persist changes
	modeling.updateProperties(element, properties);
}

/**
 * Reset text style to defaults
 * 
 * @param {Object} modeling - bpmn-js modeling service
 * @param {Object} element - BPMN element
 */
export function resetTextStyle(modeling, element) {
	if (!modeling || !element) return;

	modeling.updateProperties(element, {
		"custom:fontWeight": undefined,
		"custom:fontStyle": undefined,
		"custom:textDecoration": undefined,
		"custom:fontSize": undefined,
		"custom:textColor": undefined,
		"custom:fontFamily": undefined,
	});
}

/**
 * Convert style object to CSS style string for SVG text
 * 
 * @param {Object} style - Text style object
 * @returns {Object} CSS style properties for SVG text element
 */
export function styleToCss(style) {
	return {
		fontWeight: style.fontWeight,
		fontStyle: style.fontStyle,
		textDecoration: style.textDecoration,
		fontSize: `${style.fontSize}px`,
		fill: style.textColor,
		fontFamily: style.fontFamily,
	};
}
