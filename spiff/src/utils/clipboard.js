/**
 * Custom shared clipboard for bpmn-js
 *
 * This utility provides a singleton clipboard that persists across different
 * diagram instances, enabling copy/paste between different processes.
 */

// Shared storage for clipboard data
let globalClipboardData = {};

class CustomClipboard {
  get() {
    return globalClipboardData;
  }

  set(data) {
    globalClipboardData = data || {};
  }

  clear() {
    globalClipboardData = {};
  }

  isEmpty() {
    return !globalClipboardData || Object.keys(globalClipboardData).length === 0;
  }
}

// bpmn-js module definition
const clipboardModule = {
  clipboard: ['type', CustomClipboard]
};

export default clipboardModule;
export { CustomClipboard };
