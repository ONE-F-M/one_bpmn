import { reactive, ref } from "vue"
import { frappeRequest } from "frappe-ui"
import { dayjs } from "@/dayjs"

const FIRST_PAGE = 3
const NEXT_PAGE = 10

// One expanded issue at a time; its failed runs load on first expand and stay cached for the session.
export function useIssueRuns(queryParams) {
	const cache = reactive({})
	const expanded = ref("")

	function cacheKey(issueKey) {
		const { from_date, to_date, origin, group_by } = queryParams()
		return [issueKey, from_date, to_date, origin, group_by].join("|")
	}

	function entry(issueKey) {
		return cache[cacheKey(issueKey)] || { total: 0, runs: [], loading: false, error: null }
	}

	async function load(issueKey, more = false) {
		const id = cacheKey(issueKey)
		if (cache[id] && !more) return
		const current = cache[id] || { total: 0, runs: [], loading: false, error: null }
		cache[id] = { ...current, loading: true, error: null }
		const { from_date, to_date, origin, group_by } = queryParams()
		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.insights_api.get_issue_runs",
				method: "POST",
				params: {
					key: issueKey,
					from_date,
					to_date,
					origin,
					group_by,
					limit: more ? NEXT_PAGE : FIRST_PAGE,
					offset: current.runs.length,
				},
			})
			cache[id] = { total: response.total, runs: [...current.runs, ...response.runs], loading: false, error: null }
		} catch (err) {
			cache[id] = { ...current, loading: false, error: err }
		}
	}

	function remaining(issueKey) {
		const { total, runs } = entry(issueKey)
		return total - runs.length
	}

	function toggle(issueKey) {
		expanded.value = expanded.value === issueKey ? "" : issueKey
		if (expanded.value) load(issueKey)
	}

	return { entry, load, remaining, toggle, expanded }
}

export function errorRateClass(rate) {
	if (rate > 5) return "text-red-600"
	if (rate >= 2) return "text-amber-600"
	return "text-green-600"
}

// Within 24 hours reads as relative time; yesterday and older read as a day.
export function lastSeenText(value, __) {
	const seen = dayjs(value)
	if (!seen.isValid()) return ""
	if (dayjs().diff(seen, "hour") < 24) return seen.fromNow()
	if (seen.isSame(dayjs().subtract(1, "day"), "day")) return __("Yesterday")
	return seen.format("MMM D")
}

export function isRecent(value) {
	return dayjs().diff(dayjs(value), "hour") < 24
}
