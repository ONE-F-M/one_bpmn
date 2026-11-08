import { computed, ref } from "vue";
import { frappeRequest } from "frappe-ui";

// A paged list: `buildParams` returns the active filters, the page window is added here.
export function useA2AList({ url, rowsKey, buildParams, onError }) {
	const rows = ref([]);
	const total = ref(0);
	const start = ref(0);
	const loading = ref(false);
	// FormControl's select returns a string, and `start + "20"` is "020".
	const pageLength = ref(20);
	const pageLengthNum = computed(() => Number(pageLength.value) || 20);

	async function load(from = 0) {
		loading.value = true;
		try {
			const r = await frappeRequest({
				url,
				params: {
					...buildParams(),
					start: Math.max(0, from),
					page_length: pageLengthNum.value,
				},
			});
			rows.value = r[rowsKey] || [];
			total.value = r.total || 0;
			start.value = r.start || 0;
		} catch (e) {
			onError(e.message || String(e));
		} finally {
			loading.value = false;
		}
	}

	const prev = () => load(Math.max(0, start.value - pageLengthNum.value));
	const next = () => load(start.value + pageLengthNum.value);
	const changeSize = () => load(0);

	return {
		rows,
		total,
		start,
		loading,
		pageLength,
		pageLengthNum,
		load,
		prev,
		next,
		changeSize,
	};
}
