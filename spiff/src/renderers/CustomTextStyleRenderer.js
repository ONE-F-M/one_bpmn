/**
 * Custom Text Style Renderer Module
 * 
 * Extends BpmnRenderer to support per-element text styles.
 * This module listens for render events and applies custom text styling
 * to element labels based on properties stored in the businessObject.
 */

import { getTextStyle, hasCustomTextStyle, DEFAULT_TEXT_STYLE } from "../utils/textStyleUtils";

/**
 * Post-render hook that applies custom text styles to labels
 * We use a post-process approach to modify the rendered SVG text elements
 */
export default function CustomTextStyleModule(eventBus, elementRegistry) {
	// Listen for shape rendered events to apply custom text styles
	eventBus.on("shape.added", function (event) {
		applyTextStyle(event.element, event.gfx);
	});

	eventBus.on("shape.changed", function (event) {
		applyTextStyle(event.element, event.gfx);
	});

	// Also listen for element updates (when properties change)
	eventBus.on("element.changed", function (event) {
		const element = event.element;
		const gfx = elementRegistry.getGraphics(element);
		if (gfx) {
			applyTextStyle(element, gfx);
		}
	});
}

/**
 * Apply custom text style to an element's label
 * 
 * @param {Object} element - BPMN element
 * @param {SVGElement} gfx - SVG graphics container
 */
function applyTextStyle(element, gfx) {
	if (!element || !gfx) return;

	const style = getTextStyle(element);
	const hasCustomStyle = hasCustomTextStyle(element);
	
	// Find text elements within the shape
	const textElements = gfx.querySelectorAll("text, tspan");
	
	textElements.forEach((textEl) => {
		// Always apply text color to override stroke color affecting text
		// This is the fix for Bug #1: stroke color was changing text color
		textEl.setAttribute("fill", style.textColor);

		// Only apply other custom styles if element has custom text style set
		if (hasCustomStyle) {
			// Apply font weight
			if (style.fontWeight !== DEFAULT_TEXT_STYLE.fontWeight) {
				textEl.style.fontWeight = style.fontWeight;
			} else {
				textEl.style.fontWeight = "";
			}

			// Apply font style (italic)
			if (style.fontStyle !== DEFAULT_TEXT_STYLE.fontStyle) {
				textEl.style.fontStyle = style.fontStyle;
			} else {
				textEl.style.fontStyle = "";
			}

			// Apply text decoration (underline)
			if (style.textDecoration !== DEFAULT_TEXT_STYLE.textDecoration) {
				textEl.style.textDecoration = style.textDecoration;
			} else {
				textEl.style.textDecoration = "";
			}

			// Apply font size
			if (style.fontSize !== DEFAULT_TEXT_STYLE.fontSize) {
				textEl.style.fontSize = `${style.fontSize}px`;
			} else {
				textEl.style.fontSize = "";
			}

			// Apply font family
			if (style.fontFamily !== DEFAULT_TEXT_STYLE.fontFamily) {
				textEl.style.fontFamily = style.fontFamily;
			} else {
				textEl.style.fontFamily = "";
			}
		}
	});
}

CustomTextStyleModule.$inject = ["eventBus", "elementRegistry"];

// Module definition for bpmn-js
export const customTextStyleModule = {
	__init__: ["customTextStyleModule"],
	customTextStyleModule: ["type", CustomTextStyleModule],
};
