/**
 * Native Copy-Paste module for bpmn-js v17+ (cross-tab / cross-window)
 *
 * ## Why the original hook-on-pasteElements approach fails in v17
 *
 * bpmn-js v17 CopyPaste#paste() guards on clipboard.isEmpty() before firing
 * any event. So in the target tab the guard always trips and paste never runs.
 *
 * ## Solution
 *
 * COPY — hook `copyPaste.elementsCopied` (fires after internal clipboard is
 *        set) and ALSO write a JSON snapshot to navigator.clipboard so it
 *        survives across tabs. Internal clipboard is kept intact so
 *        same-tab paste keeps working normally.
 *
 * PASTE — keyboard listener at priority 2050 owns Ctrl/Cmd+V:
 *         1. Reads navigator.clipboard async
 *         2. If prefixed bpmn-js data found → deserialise JSON, set internal
 *            clipboard, and call copyPaste.paste() in create mode (elements
 *            follow cursor until user clicks to place)
 *         3. If no prefixed data → returns undefined (does NOT return false)
 *            so the default bpmn-js keyboard handler fires at priority 1000
 *            and handles same-tab paste normally.
 *
 *         When the Clipboard API is not available (HTTP, permission denied),
 *         the listener is not registered at all — same-tab paste falls
 *         through to the built-in handler automatically.
 *
 * ## Why we do NOT pass { element, point } to copyPaste.paste()
 *
 * Passing `{ element: root, point: center }` triggers _direct paste_ into
 * `canvas.getRootElement()`. In collaboration diagrams (pools/lanes), the
 * root is a `bpmn:Collaboration` which does NOT have `flowElements` — only
 * `bpmn:Process` does. This causes `updateSemanticParent` to crash with
 * "Cannot read properties of undefined (reading 'push')".
 *
 * Calling `copyPaste.paste()` without arguments enters "create mode" where
 * elements follow the cursor until the user clicks to place them. This lets
 * bpmn-js determine the correct parent (lane, subprocess, etc.) from the
 * drop target, avoiding the crash entirely.
 *
 * ## Serialisation / deserialisation
 *
 * Moddle instances store $type on the prototype, not as an enumerable own
 * property, so plain JSON.stringify misses it.  We use a replacer that lifts
 * $type into the serialised object.
 *
 * On parse, moddleCopy.copyElement() expects moddle instances (not plain
 * objects) as the source — otherwise its type-descriptor lookup fails.
 * We use a JSON.parse reviver that calls moddle.create() for every object
 * that carries a $type field, rebuilding the full instance hierarchy before
 * handing the tree to the clipboard.
 */

const PASTE_PRIORITY = 2050; // higher than default keyboard handler (1000)
const PREFIX = 'bpmn-js-clip----';

// ─── Clipboard API availability ───────────────────────────────────────────────
const clipboardApi = typeof navigator !== 'undefined' ? navigator.clipboard : null;
const canWrite = !!(clipboardApi?.writeText);
const canRead  = !!(clipboardApi?.readText);

// ─── Serialiser ───────────────────────────────────────────────────────────────

/**
 * JSON.stringify replacer that lifts $type from the prototype into the
 * serialised object so cross-tab deserialisation can reconstruct the type.
 */
function moddleReplacer(_key, value) {
	if (
		value !== null &&
		typeof value === 'object' &&
		value.$type &&
		!Object.prototype.hasOwnProperty.call(value, '$type')
	) {
		return Object.assign({ $type: value.$type }, value);
	}
	return value;
}

function serializeTree(tree) {
	return JSON.stringify(tree, moddleReplacer);
}

// ─── Reviver ─────────────────────────────────────────────────────────────────

/**
 * JSON.parse reviver that reconstructs moddle instances (via moddle.create)
 * from plain objects that have a $type field.
 *
 * JSON.parse runs the reviver bottom-up, so children are already moddle
 * instances by the time we process a parent — exactly what moddleCopy needs.
 */
function createReviver(moddle) {
	return function revive(_key, value) {
		if (value === null || typeof value !== 'object' || typeof value.$type !== 'string') {
			return value;
		}
		try {
			const attrs = Object.assign({}, value);
			delete attrs.$type; // moddle.create takes type separately
			return moddle.create(value.$type, attrs);
		} catch (_err) {
			// Unknown / unregistered type — return as-is so the descriptor
			// lookup in moddleCopy is at least given the plain object.
			return value;
		}
	};
}

// ─── NativeCopyPaste class ────────────────────────────────────────────────────
class NativeCopyPaste {
	constructor(eventBus, copyPaste, clipboard, moddle, keyboard) {

		const fireError = (message, error) => {
			console.warn('[native-copy-paste]', message, error);
			eventBus.fire('native-copy-paste:error', { message, error });
		};

		// ── COPY ─────────────────────────────────────────────────────────────
		// Fires after CopyPaste#copy() has already set the internal clipboard.
		// Write to system clipboard too so the data survives a tab switch.
		if (canWrite) {
			eventBus.on('copyPaste.elementsCopied', (context) => {
				if (!context.tree) return;

				let json;
				try {
					json = serializeTree(context.tree);
				} catch (err) {
					fireError('serialise failed', err);
					return;
				}

				clipboardApi.writeText(PREFIX + json)
					.catch((err) => fireError('writeText failed', err));
			});
		}

		// ── PASTE ─────────────────────────────────────────────────────────────
		// Only register the high-priority Ctrl+V intercept when the Clipboard
		// API is available (HTTPS contexts). On HTTP, skip entirely and let
		// the built-in bpmn-js keyboard handler (priority 1000) manage
		// same-tab paste without any interference.
		if (canRead) {
			keyboard.addListener(PASTE_PRIORITY, (context) => {
				const evt    = context.keyEvent;
				const isMac  = /mac/i.test(navigator.platform);
				const isPaste = (isMac ? evt.metaKey : evt.ctrlKey) && evt.key === 'v';
				if (!isPaste) return; // not our key — propagate

				evt.preventDefault();

				// Read system clipboard asynchronously.
				// We return false synchronously to stop the default handler,
				// then perform the actual paste in the .then() callback.
				clipboardApi.readText()
					.then((text) => {
						if (text?.startsWith(PREFIX)) {
							// Cross-tab path: rebuild moddle instances then populate
							// the internal clipboard so isEmpty() returns false.
							try {
								const reviver = createReviver(moddle);
								const tree = JSON.parse(text.substring(PREFIX.length), reviver);
								clipboard.set(tree);
								// Use create mode (no element/point) — elements follow
								// cursor until user clicks to place. This avoids the
								// Collaboration vs Process parent mismatch that crashes
								// updateSemanticParent in pool/lane diagrams.
								copyPaste.paste();
							} catch (err) {
								fireError('parse/revive failed — paste skipped', err);
							}
						} else {
							// No bpmn-js data in system clipboard — use same-tab
							// internal clipboard via create mode.
							if (!clipboard.isEmpty()) {
								copyPaste.paste();
							}
						}
					})
					.catch((err) => {
						// Permission denied or API unavailable —
						// fall back to same-tab internal clipboard.
						fireError('readText failed (same-tab fallback)', err);
						if (!clipboard.isEmpty()) {
							copyPaste.paste();
						}
					});

				return false; // synchronously stop all lower-priority handlers
			});
		}
	}
}

NativeCopyPaste.$inject = [
	'eventBus',
	'copyPaste',
	'clipboard',
	'moddle',
	'keyboard',
];

// ─── bpmn-js module export ────────────────────────────────────────────────────
export default {
	__init__: ['nativeCopyPaste'],
	nativeCopyPaste: ['type', NativeCopyPaste],
};
