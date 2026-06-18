import CustomShapeRenderer, { customShapeSvgStore } from './CustomShapeRenderer';

/**
 * Custom shapes module for bpmn-js
 * Registers the custom shape renderer
 */
const CustomShapesModule = {
	__init__: ['customShapeRenderer'],
	customShapeRenderer: ['type', CustomShapeRenderer]
};

export default CustomShapesModule;
export { customShapeSvgStore };
