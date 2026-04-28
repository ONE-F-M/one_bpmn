/**
 * useCurrentUser — composable that provides the logged-in user's
 * email and roles. User comes from window.frappe.boot, roles are
 * fetched once via API and cached.
 *
 * Usage:
 *   const { currentUser, currentRoles, isReady } = useCurrentUser()
 */
import { ref } from "vue"
import { frappeRequest } from "frappe-ui"

const currentUser = ref("")
const currentRoles = ref([])
const isReady = ref(false)
let fetchPromise = null

function init() {
	if (fetchPromise) return fetchPromise

	// User is available synchronously from boot
	currentUser.value = window.frappe?.boot?.session_user || ""

	// Roles need a one-time API call
	fetchPromise = (async () => {
		try {
			const res = await frappeRequest({
				url: "/api/method/frappe.core.doctype.user.user.get_roles",
				params: { uid: currentUser.value },
			})
			currentRoles.value = res.message || res || []
		} catch (e) {
			console.warn("useCurrentUser: could not fetch roles:", e)
		} finally {
			isReady.value = true
		}
	})()
	return fetchPromise
}

export function useCurrentUser() {
	if (!fetchPromise) init()
	return { currentUser, currentRoles, isReady }
}
