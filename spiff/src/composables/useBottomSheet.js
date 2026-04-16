import { ref, onScopeDispose } from "vue"

/**
 * Swipe-to-dismiss bottom-sheet composable.
 * Attach to the drag-handle element. Calls `onDismiss` when the user
 * drags > `threshold` px downward.
 */
export function useBottomSheet({ threshold = 100 } = {}) {
	const dragOffset = ref(0)
	const isDragging = ref(false)
	let startY = 0
	let handleEl = null
	let touchEndHandler = null

	function onTouchStart(e) {
		isDragging.value = true
		startY = e.touches[0].clientY
	}

	function onTouchMove(e) {
		if (!isDragging.value) return
		const dy = Math.max(0, e.touches[0].clientY - startY)
		dragOffset.value = dy
	}

	function attach(el, dismissFn) {
		// Defensively detach any prior element to prevent listener accumulation
		detach()

		handleEl = el
		if (!el) return

		// Store the exact handler reference so detach() can remove it
		touchEndHandler = () => {
			const shouldDismiss = dragOffset.value > threshold
			isDragging.value = false
			dragOffset.value = 0
			if (shouldDismiss && typeof dismissFn === "function") dismissFn()
		}

		el.addEventListener("touchstart", onTouchStart, { passive: true })
		el.addEventListener("touchmove", onTouchMove, { passive: true })
		el.addEventListener("touchend", touchEndHandler)
	}

	function detach() {
		if (!handleEl) return
		handleEl.removeEventListener("touchstart", onTouchStart)
		handleEl.removeEventListener("touchmove", onTouchMove)
		if (touchEndHandler) {
			handleEl.removeEventListener("touchend", touchEndHandler)
			touchEndHandler = null
		}
		handleEl = null
	}

	onScopeDispose(detach)

	return { dragOffset, isDragging, attach, detach }
}
