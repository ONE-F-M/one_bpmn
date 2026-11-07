import BaseRenderer from 'diagram-js/lib/draw/BaseRenderer';

const HIGH_PRIORITY = 1500;

/**
 * Custom renderer for Sticky Notes.
 * Renders bpmn:TextAnnotation elements as yellow sticky notes
 * when they have the isStickyNote attribute.
 */
export default class StickyNoteRenderer extends BaseRenderer {
	constructor(eventBus, bpmnRenderer, textRenderer) {
		super(eventBus, HIGH_PRIORITY);
		this.bpmnRenderer = bpmnRenderer;
		this.textRenderer = textRenderer;
	}

	canRender(element) {
		// Only render if it's a TextAnnotation with isStickyNote property
		return element.type === 'bpmn:TextAnnotation' && 
			   element.businessObject.get('spiffworkflow:isStickyNote');
	}

	drawShape(parentNode, element) {
		const businessObject = element.businessObject;
		const color = businessObject.get('spiffworkflow:color') || '#fff9c4'; // Default pastel yellow

		// Get element dimensions
		const width = element.width || 100;
		const height = element.height || 80;

		// Create the sticky note body
		const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
		rect.setAttribute('width', width);
		rect.setAttribute('height', height);
		rect.setAttribute('fill', color);
		rect.setAttribute('stroke', '#eab308'); // tailwind yellow-500 approx
		rect.setAttribute('stroke-width', '1');
		rect.setAttribute('rx', '2');
		rect.setAttribute('ry', '2');
		
		// Add a subtle shadow using SVG filter if possible, or just append it
		parentNode.appendChild(rect);

		// Render text
		const text = businessObject.text || '';
		if (text) {
			const textElement = this.textRenderer.createText(text, {
				box: element,
				align: 'center-middle',
				padding: 8,
				style: {
					fontSize: '13px',
					fill: '#000000' // pure black for maximum contrast
				}
			});
			parentNode.appendChild(textElement);
		}

		return rect;
	}

	getShapePath(shape) {
		const { x, y, width, height } = shape;
		return `M ${x} ${y} L ${x + width} ${y} L ${x + width} ${y + height} L ${x} ${y + height} Z`;
	}
}

StickyNoteRenderer.$inject = ['eventBus', 'bpmnRenderer', 'textRenderer'];

// Module definition for bpmn-js
export const stickyNoteModule = {
	__init__: ['stickyNoteRenderer'],
	stickyNoteRenderer: ['type', StickyNoteRenderer]
};
