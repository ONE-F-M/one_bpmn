import BaseRenderer from 'diagram-js/lib/draw/BaseRenderer';
import { getTextStyle } from '../../utils/textStyleUtils';

const HIGH_PRIORITY = 1500;
const PADDING = 8;
const MIN_HEIGHT = 80;
const LINE_HEIGHT = 1.2;

// Layout style from the note's own font settings, so line spacing and wrapping
// follow the chosen size instead of the hardcoded 13px.
function layoutStyle(element) {
	const s = getTextStyle(element);
	return {
		fontSize: s.fontSize,
		fontFamily: `${s.fontFamily}, Arial, sans-serif`,
		fontWeight: s.fontWeight,
		fontStyle: s.fontStyle,
		lineHeight: LINE_HEIGHT,
		fill: '#000000'
	};
}

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
		// Colours picked in the formatting toolbar live on the DI (bioc:*); fall back to the note's own defaults.
		const di = element.di;
		const color = (di && (di.get('bioc:fill') || di.get('color:background-color')))
			|| businessObject.get('spiffworkflow:color') || '#fff9c4'; // Default pastel yellow
		const stroke = (di && (di.get('bioc:stroke') || di.get('color:border-color'))) || '#eab308';

		// Get element dimensions
		const width = element.width || 100;
		const height = element.height || 80;

		// Create the sticky note body
		const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
		rect.setAttribute('width', width);
		rect.setAttribute('height', height);
		rect.setAttribute('fill', color);
		rect.setAttribute('stroke', stroke);
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
				padding: PADDING,
				style: layoutStyle(element)
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

/**
 * Grow/shrink a note's height to fit its text (width stays user-controlled).
 */
function StickyNoteAutoSize(eventBus, modeling, textRenderer, canvas) {
	function fit(element) {
		if (!element || !element.businessObject ||
			!element.businessObject.get('spiffworkflow:isStickyNote')) return;

		const svg = canvas._svg;
		const text = textRenderer.createText(element.businessObject.text || '', {
			box: { width: element.width, height: 100000 },
			align: 'left-top',
			padding: PADDING,
			style: layoutStyle(element)
		});
		svg.appendChild(text);
		const h = Math.ceil(text.getBBox().height) + PADDING * 2;
		svg.removeChild(text);

		const height = Math.max(MIN_HEIGHT, h);
		if (height !== Math.round(element.height)) {
			modeling.resizeShape(element, {
				x: element.x, y: element.y, width: element.width, height
			});
		}
	}

	eventBus.on([
		'commandStack.element.updateProperties.postExecuted',
		'commandStack.element.updateLabel.postExecuted'
	], ({ context }) => fit(context.element));
}

StickyNoteAutoSize.$inject = ['eventBus', 'modeling', 'textRenderer', 'canvas'];

StickyNoteRenderer.$inject = ['eventBus', 'bpmnRenderer', 'textRenderer'];

// Module definition for bpmn-js
export const stickyNoteModule = {
	__init__: ['stickyNoteRenderer', 'stickyNoteAutoSize'],
	stickyNoteAutoSize: ['type', StickyNoteAutoSize],
	stickyNoteRenderer: ['type', StickyNoteRenderer]
};
