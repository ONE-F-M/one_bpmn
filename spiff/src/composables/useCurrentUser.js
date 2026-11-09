/**
 * useCurrentUser — composable that provides the logged-in user's
 * email and roles. User comes from window.frappe.boot, roles are
 * fetched once via API and cached.
 *
 * Usage:
 *   const { currentUser, currentRoles, isReady } = useCurrentUser()
 */
import { ref } from "vue"
import { loadSessionRoles, sessionUser } from "@/stores/session"

const currentUser = ref("")
const currentRoles = ref([])
const isReady = ref(false)
let fetchPromise = null

function init() {
	if (fetchPromise) return fetchPromise

	currentUser.value = sessionUser()

	fetchPromise = loadSessionRoles()
		.then((roles) => {
			currentRoles.value = roles || []
		})
		.catch((e) => {
			console.warn("useCurrentUser: could not fetch roles:", e)
		})
		.finally(() => {
			isReady.value = true
		})
	return fetchPromise
}

export function useCurrentUser() {
	if (!fetchPromise) init()
	return { currentUser, currentRoles, isReady }
}
