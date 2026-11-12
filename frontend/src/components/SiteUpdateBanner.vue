<template>
	<div
		v-if="endsAt !== null"
		role="alert"
		class="fixed top-0 inset-x-0 z-[300] bg-red-600 text-white text-center text-sm font-semibold px-4 py-2 shadow-md"
	>
		{{ message }}
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { frappeRequest } from "frappe-ui"

// One place to adjust if the server method or event is renamed.
const COUNTDOWN_METHOD = "one_bpmn.api.site_update.get_site_update_countdown"
const COUNTDOWN_EVENT = "site_update_countdown"

// Frappe's __() when the desk runtime is present; identity otherwise.
function translate(text, args = []) {
	const out = typeof window.__ === "function" ? window.__(text, args) : text
	return args.reduce((s, a, i) => s.replace(`{${i}}`, a), out)
}

const endsAt = ref(null) // epoch ms, null = no countdown
const now = ref(Date.now())
let timer = null

// The server sends UTC; a bare timestamp without an offset must not be read as local time.
function parseUtc(iso) {
	if (!iso) return NaN
	return Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`)
}

const secondsLeft = computed(() => (endsAt.value === null ? 0 : Math.max(0, Math.ceil((endsAt.value - now.value) / 1000))))
const clock = computed(() => {
	const pad = (n) => String(n).padStart(2, "0")
	return `${pad(Math.floor(secondsLeft.value / 60))}:${pad(secondsLeft.value % 60)}`
})
const message = computed(() =>
	translate("This site will become unavailable in {0}. Any unsaved work will be lost.", [clock.value]),
)

function stop() {
	clearInterval(timer)
	timer = null
	endsAt.value = null
}

function tick() {
	now.value = Date.now()
	if (endsAt.value !== null && endsAt.value <= now.value) stop()
}

function start(payload) {
	if (!payload || payload.cancelled || payload.active === false) return stop()
	let end = parseUtc(payload.ends_at)
	if (Number.isNaN(end) && Number.isFinite(payload.seconds_remaining)) {
		end = Date.now() + payload.seconds_remaining * 1000
	}
	if (Number.isNaN(end)) return stop()
	clearInterval(timer)
	endsAt.value = end
	now.value = Date.now()
	timer = setInterval(tick, 1000)
	tick()
}

async function loadCurrent() {
	try {
		start(await frappeRequest({ url: `/api/method/${COUNTDOWN_METHOD}` }))
	} catch (e) {
		// No countdown information available: show nothing.
	}
}

onMounted(() => {
	window.frappe?.realtime?.on(COUNTDOWN_EVENT, start)
	loadCurrent()
})

onBeforeUnmount(() => {
	window.frappe?.realtime?.off(COUNTDOWN_EVENT, start)
	clearInterval(timer)
})
</script>
