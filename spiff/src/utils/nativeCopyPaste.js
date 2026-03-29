/**
 * Native Copy-Paste module for bpmn-js v17 (cross-tab / cross-window)
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
 *        survives across tabs. Keep internal clipboard populated too so
 *        same-tab paste keeps working normally.
 *
 * PASTE — keyboard listener at priority 2050 owns Ctrl/Cmd+V:
 *         1. Synchronously returns false (stops all lower-priority handlers)
 *         2. Reads navigator.clipboard async
 *         3. Deserialises JSON → proper moddle instances via moddle.create()
 *         4. Sets the internal clipboard (so isEmpty() → false)
 *         5. Calls copyPaste.paste() at canvas centre
 *         Falls back to same-tab internal clipboard if readText() fails.
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
	constructor(eventBus, copyPaste, clipboard, moddle, keyboard, canvas) {

		// ── COPY ─────────────────────────────────────────────────────────────
		// Fires after CopyPaste#copy() has already set the internal clipboard.
		// Write to system clipboard too so the data survives a tab switch.
		eventBus.on('copyPaste.elementsCopied', (context) => {
			if (!context.tree) return;
			let json;
			try {
				json = serializeTree(context.tree);
			} catch (err) {
				console.warn('[native-copy-paste] serialise failed:', err);
				return;
			}
			navigator.clipboard
				.writeText(PREFIX + json)
				.catch((err) => console.warn('[native-copy-paste] writeText failed:', err));
		});

		// ── PASTE ─────────────────────────────────────────────────────────────
		// High-priority keyboard intercept for Ctrl/Cmd+V.
		keyboard.addListener(PASTE_PRIORITY, (context) => {
			const evt    = context.keyEvent;
			const isMac  = /mac/i.test(navigator.platform);
			const isPaste = (isMac ? evt.metaKey : evt.ctrlKey) && evt.key === 'v';
			if (!isPaste) return; // not our key — propagate

			evt.preventDefault();

			const viewbox = canvas.viewbox();
			const root    = canvas.getRootElement();
			const center  = {
				x: viewbox.x + viewbox.width  / 2,
				y: viewbox.y + viewbox.height / 2,
			};

			const doPaste = () => {
				if (!clipboard.isEmpty()) {
					copyPaste.paste({ element: root, point: center });
				}
			};

			navigator.clipboard
				.readText()
				.then((text) => {
					if (text?.startsWith(PREFIX)) {
						// Cross-tab path: rebuild moddle instances then populate
						// the internal clipboard so isEmpty() returns false.
						try {
							const reviver = createReviver(moddle);
							const tree = JSON.parse(text.substring(PREFIX.length), reviver);
							clipboard.set(tree);
						} catch (err) {
							console.warn('[native-copy-paste] parse/revive failed:', err);
						}
					}
					doPaste();
				})
				.catch((err) => {
					// Clipboard permission denied or API unavailable —
					// fall back to whatever is in the same-tab clipboard.
					console.warn('[native-copy-paste] readText failed (same-tab fallback):', err);
					doPaste();
				});

			return false; // synchronously stop all lower-priority handlers
		});
	}
}

NativeCopyPaste.$inject = [
	'eventBus',
	'copyPaste',
	'clipboard',
	'moddle',
	'keyboard',
	'canvas',
];

// ─── bpmn-js module export ────────────────────────────────────────────────────
export default {
	__init__: ['nativeCopyPaste'],
	nativeCopyPaste: ['type', NativeCopyPaste],
};
