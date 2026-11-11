import { ref, onMounted, onScopeDispose } from "vue"

/**
 * Reactive window-size tracker.
 * Returns `isMobile` (< 640px) and `isTablet` (< 768px) booleans.
 */
export function useWindowSize() {
	const width = ref(window.innerWidth)
	const isMobile = ref(window.innerWidth < 640)
	const isTablet = ref(window.innerWidth < 768)

	function update() {
		width.value = window.innerWidth
		isMobile.value = window.innerWidth < 640
		isTablet.value = window.innerWidth < 768
	}

	onMounted(() => window.addEventListener("resize", update))
	onScopeDispose(() => window.removeEventListener("resize", update))

	return { width, isMobile, isTablet }
}
