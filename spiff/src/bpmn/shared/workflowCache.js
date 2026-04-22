/**
 * workflowCache.js
 *
 * Shared async caches for Workflow and Workflow State dropdowns.
 * Used by StartEventProps and ConditionalStartEventProps.
 */

import { frappeGet } from "./frappeResource";

// ---------------------------------------------------------------------------
// Cache stores (single instance, shared across all providers)
// ---------------------------------------------------------------------------
export const workflowCache = new Map();
const _workflowFetching = new Set();

export const workflowStateCache = new Map();
const _workflowStateFetching = new Set();

// ---------------------------------------------------------------------------
// Loaders
// ---------------------------------------------------------------------------

/**
 * Load active workflows for a given DocType, calling `onLoaded` with the
 * option list once available.  Results are cached — subsequent calls for the
 * same DocType return immediately from cache.
 */
export function loadWorkflows(doctype, onLoaded) {
	if (!doctype) return;
	if (workflowCache.has(doctype)) {
		onLoaded(workflowCache.get(doctype));
		return;
	}
	if (_workflowFetching.has(doctype)) return;
	_workflowFetching.add(doctype);

	frappeGet("/api/resource/Workflow", {
		fields: '["name"]',
		filters: JSON.stringify([
			["document_type", "=", doctype],
			["is_active", "=", 1],
		]),
		limit_page_length: 100,
	})
		.then((data) => {
			const list = Array.isArray(data) ? data : [];
			const options = [
				{ label: "-- Select Workflow --", value: "" },
				...list.map((d) => ({ label: d.name, value: d.name })),
			];
			workflowCache.set(doctype, options);
			_workflowFetching.delete(doctype);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[workflowCache] fetch Workflows:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			workflowCache.set(doctype, err);
			_workflowFetching.delete(doctype);
			onLoaded(err);
		});
}

/**
 * Load states for a specific Workflow, calling `onLoaded` with the option
 * list once available.  Results are cached per workflow name.
 */
export function loadWorkflowStates(workflowName, onLoaded) {
	if (!workflowName) return;
	if (workflowStateCache.has(workflowName)) {
		onLoaded(workflowStateCache.get(workflowName));
		return;
	}
	if (_workflowStateFetching.has(workflowName)) return;
	_workflowStateFetching.add(workflowName);

	frappeGet(`/api/resource/Workflow/${encodeURIComponent(workflowName)}`)
		.then((doc) => {
			const states = doc && doc.states ? doc.states : [];
			const options = [
				{ label: "-- Select State --", value: "" },
				...states.map((s) => ({ label: s.state, value: s.state })),
			];
			workflowStateCache.set(workflowName, options);
			_workflowStateFetching.delete(workflowName);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[workflowCache] fetch Workflow States:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			workflowStateCache.set(workflowName, err);
			_workflowStateFetching.delete(workflowName);
			onLoaded(err);
		});
}
