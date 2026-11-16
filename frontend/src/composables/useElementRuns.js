import { reactive, ref } from "vue"
import { frappeRequest } from "frappe-ui"

const FIRST_PAGE = 3
const NEXT_PAGE = 10
const EMPTY = { split: null, steps: [], total: 0, runs: [], loading: false, error: null }

// An element's time split and slowest runs load on first expand, cached per filter set.
export function useElementRuns(queryParams) {
	const cache = reactive({})
	const expanded = ref(new Set())

	function cacheKey(elementKey) {
		return JSON.stringify([elementKey, queryParams()])
	}

	function entry(elementKey) {
		return cache[cacheKey(elementKey)] || EMPTY
	}

	async function load(element, more = false) {
		const id = cacheKey(element.key)
		if (cache[id] && !more) return
		const current = cache[id] || EMPTY
		cache[id] = { ...current, loading: true, error: null }
		const filters = { ...queryParams(), key: element.key }
		const runsParams = {
			...filters,
			min_agent_latency_ms: element.p95_ms,
			limit: more ? NEXT_PAGE : FIRST_PAGE,
			offset: current.runs.length,
		}
		try {
			const [report, page] = await Promise.all([
				more
					? { split: current.split, rows: current.steps }
					: frappeRequest({
							url: "/api/method/processa.api.insights.get_step_latency_report",
							method: "POST",
							params: { ...filters, limit: FIRST_PAGE },
						}),
				frappeRequest({
					url: "/api/method/processa.api.insights.get_element_runs",
					method: "POST",
					params: runsParams,
				}),
			])
			cache[id] = {
				split: report.split,
				steps: report.rows,
				total: page.total,
				runs: [...current.runs, ...page.runs],
				loading: false,
				error: null,
			}
		} catch (err) {
			cache[id] = { ...current, loading: false, error: err }
		}
	}

	function remaining(elementKey) {
		const { total, runs } = entry(elementKey)
		return total - runs.length
	}

	function isExpanded(elementKey) {
		return expanded.value.has(elementKey)
	}

	function toggle(element) {
		const next = new Set(expanded.value)
		if (next.has(element.key)) next.delete(element.key)
		else next.add(element.key)
		expanded.value = next
		if (next.has(element.key)) load(element)
	}

	// A refetch collapses every row and drops runs loaded under the old filters.
	function reset() {
		expanded.value = new Set()
		Object.keys(cache).forEach((id) => delete cache[id])
	}

	return { entry, load, remaining, toggle, isExpanded, reset }
}
