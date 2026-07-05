/**
 * Direct touch handler for bpmn-js canvas.
 *
 * Attaches native DOM touch listeners to the canvas container element and
 * translates gestures into canvas.zoom() / canvas.scroll() calls.
 *
 * Supports:
 *   - One-finger drag → pan (canvas.scroll)
 *   - Two-finger pinch → zoom (canvas.zoom)
 *   - Two-finger drag → pan (canvas.scroll)
 *   - iOS Safari gesturechange → zoom (for devices where touchstart
 *     for the second finger is consumed by the browser)
 *
 * @param {import('bpmn-js').default} viewerOrModeler — bpmn-js instance
 * @param {HTMLElement} containerEl — the DOM element wrapping the canvas
 * @returns {() => void} cleanup function to remove all listeners
 */
export function setupCanvasTouchHandler(viewerOrModeler, containerEl) {
	if (!viewerOrModeler || !containerEl) return () => {}

	let canvas
	try {
		canvas = viewerOrModeler.get("canvas")
	} catch {
		return () => {}
	}
	if (!canvas) return () => {}

	// ── State ──
	let panActive = false
	let lastPanX = 0
	let lastPanY = 0

	let pinchActive = false
	let pinchStartDist = 0
	let pinchInitialZoom = 1
	let lastPinchCenterX = 0
	let lastPinchCenterY = 0

	// ── Helpers ──
	function dist(ax, ay, bx, by) {
		return Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
	}

	function getCurrentZoom() {
		try { return canvas.zoom() } catch { return 1 }
	}

	function clampZoom(z) {
		return Math.min(4, Math.max(0.2, z))
	}

	// ── Start pinch (called from both touchstart and touchmove) ──
	function startPinch(t0, t1) {
		panActive = false
		pinchActive = true
		pinchStartDist = dist(t0.clientX, t0.clientY, t1.clientX, t1.clientY)
		pinchInitialZoom = getCurrentZoom()
		lastPinchCenterX = (t0.clientX + t1.clientX) / 2
		lastPinchCenterY = (t0.clientY + t1.clientY) / 2
	}

	// ── Handlers ──
	function onTouchStart(e) {
		if (e.touches.length >= 2) {
			// Start or re-start pinch
			e.preventDefault()
			e.stopPropagation()
			startPinch(e.touches[0], e.touches[1])
			return
		}

		if (e.touches.length === 1 && !pinchActive) {
			// Start single-finger pan
			panActive = true
			lastPanX = e.touches[0].clientX
			lastPanY = e.touches[0].clientY
			// Don't preventDefault here — allow taps to pass through for element clicks
		}
	}

	function onTouchMove(e) {
		// ── Two fingers: ALWAYS handle as pinch ──
		// This catches pinch even if the second touchstart was consumed by the browser
		if (e.touches.length >= 2) {
			e.preventDefault()
			e.stopPropagation()

			const t0 = e.touches[0]
			const t1 = e.touches[1]

			// If pinch wasn't started yet (missed touchstart), start it now
			if (!pinchActive) {
				startPinch(t0, t1)
				return // first frame just initializes — apply zoom from next frame
			}

			const cx = (t0.clientX + t1.clientX) / 2
			const cy = (t0.clientY + t1.clientY) / 2

			// Zoom
			const currentDist = dist(t0.clientX, t0.clientY, t1.clientX, t1.clientY)
			if (pinchStartDist > 0) {
				const scale = currentDist / pinchStartDist
				const newZoom = clampZoom(pinchInitialZoom * scale)
				try {
					canvas.zoom(newZoom, { x: cx, y: cy })
				} catch {
					// ignore
				}
			}

			// Two-finger pan
			const dx = cx - lastPinchCenterX
			const dy = cy - lastPinchCenterY
			if (isFinite(dx) && isFinite(dy) && (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5)) {
				try { canvas.scroll({ dx, dy }) } catch {}
			}
			lastPinchCenterX = cx
			lastPinchCenterY = cy
			return
		}

		// ── One finger: pan ──
		if (panActive && e.touches.length === 1) {
			e.preventDefault()
			const t = e.touches[0]
			const dx = t.clientX - lastPanX
			const dy = t.clientY - lastPanY
			if (isFinite(dx) && isFinite(dy)) {
				try { canvas.scroll({ dx, dy }) } catch {}
			}
			lastPanX = t.clientX
			lastPanY = t.clientY
		}
	}

	function onTouchEnd(e) {
		if (e.touches.length < 2) {
			pinchActive = false
			pinchStartDist = 0
		}
		if (e.touches.length === 0) {
			panActive = false
			pinchActive = false
		}
	}

	// ── iOS Safari: gesturestart/gesturechange events ──
	// iOS Safari fires proprietary gesture events for pinch-to-zoom.
	// These fire even when touchstart for the second finger is consumed
	// by the browser's native zoom handler. Preventing default on these
	// stops the native zoom and lets our touchmove handler take over.
	let gestureInitialZoom = 1

	function onGestureStart(e) {
		e.preventDefault()
		gestureInitialZoom = getCurrentZoom()
	}

	function onGestureChange(e) {
		e.preventDefault()
		if (e.scale && isFinite(e.scale)) {
			const newZoom = clampZoom(gestureInitialZoom * e.scale)
			try {
				// Use page center as zoom origin since gesture events
				// don't provide reliable screen coordinates
				const rect = containerEl.getBoundingClientRect()
				const cx = rect.left + rect.width / 2
				const cy = rect.top + rect.height / 2
				canvas.zoom(newZoom, { x: cx, y: cy })
			} catch {
				// ignore
			}
		}
	}

	function onGestureEnd(e) {
		e.preventDefault()
	}

	// ── Attach ──
	const opts = { passive: false, capture: true }
	containerEl.addEventListener("touchstart", onTouchStart, opts)
	containerEl.addEventListener("touchmove", onTouchMove, opts)
	containerEl.addEventListener("touchend", onTouchEnd, opts)
	containerEl.addEventListener("touchcancel", onTouchEnd, opts)

	// iOS gesture events (non-standard but required for Safari)
	containerEl.addEventListener("gesturestart", onGestureStart, { passive: false })
	containerEl.addEventListener("gesturechange", onGestureChange, { passive: false })
	containerEl.addEventListener("gestureend", onGestureEnd, { passive: false })

	// ── Cleanup ──
	return function cleanup() {
		containerEl.removeEventListener("touchstart", onTouchStart, opts)
		containerEl.removeEventListener("touchmove", onTouchMove, opts)
		containerEl.removeEventListener("touchend", onTouchEnd, opts)
		containerEl.removeEventListener("touchcancel", onTouchEnd, opts)
		containerEl.removeEventListener("gesturestart", onGestureStart)
		containerEl.removeEventListener("gesturechange", onGestureChange)
		containerEl.removeEventListener("gestureend", onGestureEnd)
	}
}
