// Shared cache of the connector manifests served by the backend
// (one_bpmn.one_bpmn.connectors.api.get_connector_manifests).
//
// Connectors are configuration (the BPMN Connector / Operation / Field
// DocTypes), so everything the editor knows about them — labels, operations,
// fields, and the canvas icon — arrives from this one fetch. Two consumers share
// it: the Service Task properties panel (connectorEntries.js) and the canvas
// icon renderer (renderers/ServiceTaskIconRenderer.js). Keeping the cache here
// means a connector added in the desk shows up in both places without a rebuild.
//
// The properties panel builds its entry list synchronously and the renderer
// draws synchronously, so the fetch is fired once at module level and callers
// re-render when it resolves (fire "elements.changed", or the canvas's own
// redraw).

import { frappeGet } from "./frappeResource";

const MANIFEST_ENDPOINT = "/api/method/one_bpmn.one_bpmn.connectors.api.get_connector_manifests";
const CHOICES_ENDPOINT = "/api/method/one_bpmn.one_bpmn.connectors.api.get_connector_field_choices";

let MANIFESTS = null; // null = not loaded yet; array once loaded
let LOADING = null;

const CHOICES = {}; // source -> [{label,value}]
const CHOICES_LOADING = {};

/** The loaded manifests, or null while the fetch is still in flight. */
export function getManifests() {
	return MANIFESTS;
}

/** The manifest for a connectorId, or null (also null while loading). */
export function findManifest(connectorId) {
	return (MANIFESTS || []).find((m) => m.connectorId === connectorId) || null;
}

/**
 * Kick off the one-time manifest fetch, then notify.
 *
 * @param {Function} onLoaded called once the manifests are available (or failed)
 */
export function ensureManifests(onLoaded) {
	if (MANIFESTS !== null) return;
	if (!LOADING) {
		LOADING = frappeGet(MANIFEST_ENDPOINT)
			.then((res) => {
				MANIFESTS = Array.isArray(res) ? res : (res && res.message) || [];
			})
			.catch(() => {
				MANIFESTS = [];
			});
	}
	if (onLoaded) {
		LOADING.then(() => {
			try {
				onLoaded();
			} catch (e) {
				/* nothing mounted — the next render picks up the cache */
			}
		});
	}
}

/** Convenience wrapper for consumers holding an eventBus + element. */
export function ensureManifestsForElement(eventBus, element) {
	ensureManifests(() => {
		eventBus && eventBus.fire("elements.changed", { elements: [element] });
	});
}

// ── Dynamic dropdowns ───────────────────────────────────────────────────────
// A field configured with a Choices From path gets its options from the backend.
// The path itself is never sent from here — the server reads it from the field's
// configuration — so a request identifies the field, and carries the sibling
// field values the modeler has filled in as `context` (that is what lets a file
// dropdown list the contents of the folder chosen in another field).

/** Cache key for one field's options, including the context they depend on. */
export function choicesKey(connectorId, operation, fieldName, context) {
	return `${connectorId}::${operation}::${fieldName}::${JSON.stringify(context || {})}`;
}

export function getChoices(key) {
	return CHOICES[key];
}

export function ensureChoices(connectorId, operation, fieldName, context, eventBus, element) {
	const key = choicesKey(connectorId, operation, fieldName, context);
	if (CHOICES[key]) return key;
	if (!CHOICES_LOADING[key]) {
		CHOICES_LOADING[key] = frappeGet(CHOICES_ENDPOINT, {
			connector_id: connectorId,
			operation,
			field_name: fieldName,
			context: JSON.stringify(context || {}),
		})
			.then((res) => {
				CHOICES[key] = Array.isArray(res) ? res : (res && res.message) || [];
			})
			.catch(() => {
				CHOICES[key] = [];
			});
	}
	CHOICES_LOADING[key].then(() => {
		try {
			eventBus && eventBus.fire("elements.changed", { elements: [element] });
		} catch (e) {
			/* next render picks up the cache */
		}
	});
	return key;
}

/**
 * The canvas icon configured on a connector, or null to fall back to the
 * default plug. Shape: { path, color, label } — path is SVG path data on a
 * 24×24 viewBox, exactly what BPMN Connector stores.
 */
export function getConnectorIcon(connectorId) {
	const manifest = findManifest(connectorId);
	const icon = manifest && manifest.icon;
	if (!icon || typeof icon !== "object" || !icon.path) return null;
	return {
		path: icon.path,
		color: icon.color || "#14b8a6",
		label: icon.label || manifest.label || connectorId,
		stroke: !!icon.stroke,
	};
}
