import BaseRenderer from 'diagram-js/lib/draw/BaseRenderer';

const HIGH_PRIORITY = 1500;

// Global store for custom shape SVG content
// Maps element ID -> SVG content string
export const customShapeSvgStore = new Map();

/**
 * Custom renderer for shapes with custom SVG content.
 * Renders the SVG instead of default BPMN element rendering
 * when the element has SVG stored in customShapeSvgStore.
 */
export default class CustomShapeRenderer extends BaseRenderer {
	constructor(eventBus, bpmnRenderer) {
		super(eventBus, HIGH_PRIORITY);
		this.bpmnRenderer = bpmnRenderer;
	}

	canRender(element) {
		// Only render if element has custom shape SVG in store
		return customShapeSvgStore.has(element.id);
	}

	drawShape(parentNode, element) {
		const svgContent = customShapeSvgStore.get(element.id);

		if (!svgContent) {
			// Fallback to default renderer
			return this.bpmnRenderer.drawShape(parentNode, element);
		}

		// Get element dimensions
		const width = element.width || 100;
		const height = element.height || 80;

		// Create white background
		const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
		bg.setAttribute('width', width);
		bg.setAttribute('height', height);
		bg.setAttribute('fill', 'white');
		bg.setAttribute('stroke', '#999');
		bg.setAttribute('stroke-width', '2');
		bg.setAttribute('rx', '8');
		bg.setAttribute('ry', '8');
		parentNode.appendChild(bg);

		// Create a group for the SVG content
		const svgGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
		
		// Parse the SVG content
		const parser = new DOMParser();
		const svgDoc = parser.parseFromString(svgContent, 'image/svg+xml');
		const svgElement = svgDoc.documentElement;

		if (svgElement && svgElement.tagName === 'svg') {
			// Get original viewBox or dimensions
			const viewBox = svgElement.getAttribute('viewBox');
			let origWidth = parseFloat(svgElement.getAttribute('width')) || 100;
			let origHeight = parseFloat(svgElement.getAttribute('height')) || 100;

			if (viewBox) {
				const parts = viewBox.split(/\s+|,/);
				if (parts.length >= 4) {
					origWidth = parseFloat(parts[2]);
					origHeight = parseFloat(parts[3]);
				}
			}

			// Calculate scale to fit within element (with padding)
			const padding = 16;
			const scaleX = (width - padding * 2) / origWidth;
			const scaleY = (height - padding * 2) / origHeight;
			const scale = Math.min(scaleX, scaleY, 1); // Don't scale up more than 1

			// Calculate centering offset
			const scaledWidth = origWidth * scale;
			const scaledHeight = origHeight * scale;
			const offsetX = (width - scaledWidth) / 2;
			const offsetY = (height - scaledHeight) / 2;

			// Apply transform
			svgGroup.setAttribute('transform', `translate(${offsetX}, ${offsetY}) scale(${scale})`);

			// Copy all children from the SVG
			Array.from(svgElement.childNodes).forEach(child => {
				if (child.nodeType === Node.ELEMENT_NODE) {
					svgGroup.appendChild(child.cloneNode(true));
				}
			});
		}

		parentNode.appendChild(svgGroup);

		return bg;
	}

	getShapePath(shape) {
		// Return rectangular path for connections
		const { x, y, width, height } = shape;
		return `M ${x} ${y} L ${x + width} ${y} L ${x + width} ${y + height} L ${x} ${y + height} Z`;
	}
}

CustomShapeRenderer.$inject = ['eventBus', 'bpmnRenderer'];
