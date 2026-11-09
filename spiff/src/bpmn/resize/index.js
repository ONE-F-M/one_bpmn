/**
 * Task resize + auto-fit label module.
 *
 * Enables manual resizing of Task/CallActivity/SubProcess shapes and
 * automatically expands shapes when their label text doesn't fit.
 */

import ResizeTask from './ResizeTask';
import LabelAutoResize from './LabelAutoResize';

export default {
	__init__: ['resizeTask', 'labelAutoResize'],
	resizeTask: ['type', ResizeTask],
	labelAutoResize: ['type', LabelAutoResize]
};
