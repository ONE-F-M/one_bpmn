/**
 * ResizeTask — allows Tasks, CallActivities, and SubProcesses to be
 * manually resized via drag handles.
 *
 * Inlined from bpmn-js-task-resize (MIT) and adapted to use
 * `inherits-browser` (project standard).
 */

import RuleProvider from 'diagram-js/lib/features/rules/RuleProvider';
import inherits from 'inherits-browser';

export default function ResizeTask(eventBus, taskResizingEnabled) {
	RuleProvider.call(this, eventBus);
	this.taskResizingEnabled = taskResizingEnabled || false;
}

inherits(ResizeTask, RuleProvider);

ResizeTask.$inject = ['eventBus', 'config.taskResizingEnabled'];

ResizeTask.prototype.init = function () {
	var me = this;

	me.addRule('shape.resize', 1500, function (data) {
		if (
			me.taskResizingEnabled &&
			data.shape.businessObject &&
			(data.shape.businessObject.$instanceOf('bpmn:Task') ||
				data.shape.businessObject.$instanceOf('bpmn:CallActivity') ||
				data.shape.businessObject.$instanceOf('bpmn:SubProcess'))
		) {
			if (data.newBounds) {
				data.newBounds.width = Math.max(100, data.newBounds.width);
				data.newBounds.height = Math.max(60, data.newBounds.height);
			}
			return true;
		}
	});
};
