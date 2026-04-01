/**
 * LabelAutoResize — automatically resizes task shapes so that the label
 * text fits inside the shape without overflowing or clipping.
 *
 * Uses bpmn-js's own TextRenderer to compute how text will be laid out
 * inside the shape (matching the exact same word-wrapping logic used
 * during rendering). If the rendered text overflows the shape, it
 * expands the shape height (and optionally width) just enough to fit.
 *
 * Applies to: bpmn:Task, bpmn:CallActivity, bpmn:SubProcess (collapsed)
 */

const LABEL_PADDING = 7;  // matches BpmnRenderer's renderEmbeddedLabel padding
const MIN_WIDTH = 100;
const MIN_HEIGHT = 60;

export default function LabelAutoResize(eventBus, modeling, textRenderer, elementRegistry) {

	// After a label update command is executed, check if the shape needs resizing
	eventBus.on('commandStack.element.updateLabel.postExecute', function (event) {
		var context = event.context;
		var element = context.element;
		if (shouldAutoResize(element)) {
			autoResizeShape(element);
		}
	});

	// Also handle direct property updates (e.g. from properties panel)
	eventBus.on('commandStack.element.updateProperties.postExecute', function (event) {
		var context = event.context;
		var element = context.element;
		var properties = context.properties;

		if (!properties || !('name' in properties)) return;
		if (shouldAutoResize(element)) {
			autoResizeShape(element);
		}
	});

	// After import completes, auto-fit all task shapes
	eventBus.on('import.done', function () {
		var elements = elementRegistry.getAll();
		elements.forEach(function (element) {
			if (shouldAutoResize(element)) {
				var name = element.businessObject.get('name') || '';
				if (name.trim()) {
					autoResizeShape(element);
				}
			}
		});
	});

	function shouldAutoResize(element) {
		if (!element || !element.businessObject) return false;
		// Skip label elements (external labels)
		if (element.labelTarget) return false;

		var bo = element.businessObject;
		return (
			bo.$instanceOf('bpmn:Task') ||
			bo.$instanceOf('bpmn:CallActivity') ||
			bo.$instanceOf('bpmn:SubProcess')
		);
	}

	function autoResizeShape(element) {
		var text = (element.businessObject.get('name') || '').trim();
		if (!text) return;

		// Use the textRenderer to compute text layout dimensions
		// This matches exactly how BpmnRenderer.renderEmbeddedLabel works:
		// it calls textRenderer.createText with box = element bounds, padding = 7, align = center-middle
		var textDimensions = textRenderer.createText(text, {
			box: {
				width: element.width,
				height: element.height
			},
			padding: LABEL_PADDING,
			align: 'center-middle'
		});

		// Get the actual rendered text bounding box
		// The text element contains tspan children; check the last tspan's y to determine total height
		var tspans = textDimensions.querySelectorAll('tspan');
		if (!tspans || tspans.length === 0) return;

		var defaultStyle = textRenderer.getDefaultStyle();
		var fontSize = parseInt(defaultStyle.fontSize, 10) || 12;
		var lineHeightRatio = defaultStyle.lineHeight || 1.2;
		var lineHeight = lineHeightRatio * fontSize;

		// Total text height = number of lines × line height
		var totalTextHeight = tspans.length * lineHeight;

		// Required height = text height + padding on both sides
		var requiredHeight = totalTextHeight + LABEL_PADDING * 2;

		// Check if the text fits in the current shape
		var currentWidth = element.width;
		var currentHeight = element.height;

		var needsResize = false;
		var finalWidth = currentWidth;
		var finalHeight = currentHeight;

		// If the text doesn't fit vertically, expand height
		if (requiredHeight > currentHeight) {
			finalHeight = Math.max(MIN_HEIGHT, Math.ceil(requiredHeight));
			needsResize = true;
		}

		// Also check if lines are still being clipped at the current width
		// by checking the widest tspan against available width
		var widestLineWidth = 0;
		// Temporarily attach SVG element to DOM to measure
		var helperSvg = document.getElementById('helper-svg');
		if (!helperSvg) {
			helperSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
			helperSvg.id = 'helper-svg-resize';
			helperSvg.style.cssText = 'position:absolute;left:-9999px;top:-9999px;visibility:hidden;width:0;height:0;';
			document.body.appendChild(helperSvg);
		}
		helperSvg.appendChild(textDimensions);
		for (var i = 0; i < tspans.length; i++) {
			var len = tspans[i].getComputedTextLength ? tspans[i].getComputedTextLength() : 0;
			if (len > widestLineWidth) widestLineWidth = len;
		}
		helperSvg.removeChild(textDimensions);

		var requiredWidth = widestLineWidth + LABEL_PADDING * 2;
		if (requiredWidth > currentWidth) {
			finalWidth = Math.max(MIN_WIDTH, Math.ceil(requiredWidth));
			needsResize = true;
		}

		if (!needsResize) return;

		// Calculate the new bounds centered around the shape's center
		var cx = element.x + currentWidth / 2;
		var cy = element.y + currentHeight / 2;

		var newBounds = {
			x: Math.round(cx - finalWidth / 2),
			y: Math.round(cy - finalHeight / 2),
			width: Math.round(finalWidth),
			height: Math.round(finalHeight)
		};

		modeling.resizeShape(element, newBounds);
	}
}

LabelAutoResize.$inject = ['eventBus', 'modeling', 'textRenderer', 'elementRegistry'];
