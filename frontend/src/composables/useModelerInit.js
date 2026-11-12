/**
 * useModelerInit — composable that initialises a bpmn-js BpmnModeler with a
 * retry loop to work around the Preact __H hook-state conflict that can occur
 * when bpmn-js-spiffworkflow's bundled Preact races with the properties-panel
 * Preact on first mount.  Each failed attempt destroys the partially-created
 * modeler so Preact can reset its state, then waits a short back-off before
 * retrying.
 *
 * @param {Object} options
 * @param {import('vue').Ref} options.container         - ref to the canvas DOM element
 * @param {import('vue').Ref} options.propertiesContainer - ref to the properties-panel DOM element
 * @param {Object}            options.modelerConfig      - extra options forwarded to BpmnModeler
 * @param {Function}          options.onReady            - called once on successful init
 * @param {Function}          options.onError            - called if all attempts fail
 * @param {number}            [options.maxAttempts=3]    - how many times to retry
 */
export async function initModeler({
	container,
	propertiesContainer,
	modelerConfig,
	onReady,
	onError,
	maxAttempts = 3,
}) {
	let modeler = null;
	let lastErr;

	for (let attempt = 0; attempt < maxAttempts; attempt++) {
		if (attempt > 0) {
			// Destroy any partially-initialised modeler so Preact can reset
			if (modeler) {
				try {
					modeler.destroy();
				} catch (_) {}
				modeler = null;
			}
			// Brief back-off so the Preact unmount can complete
			await new Promise((resolve) => setTimeout(resolve, 150 * attempt));
		}

		try {
			const BpmnModeler = (await import("bpmn-js/lib/Modeler")).default;

			modeler = new BpmnModeler({
				container: container.value,
				propertiesPanel: {
					parent: propertiesContainer.value,
				},
				...modelerConfig,
			});

			await onReady(modeler);
			return modeler; // success – exit retry loop
		} catch (err) {
			lastErr = err;
			console.warn(
				`BpmnModeler init attempt ${attempt + 1} failed: ${err.message}`
			);
		}
	}

	console.error(
		`Failed to initialise BPMN modeler after ${maxAttempts} attempts:`,
		lastErr
	);
	if (onError) onError(lastErr);
	return null;
}
