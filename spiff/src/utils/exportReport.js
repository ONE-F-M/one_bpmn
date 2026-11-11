// A report export replies with a file, so the browser navigates to the endpoint instead of fetching it.
export function openReportExport(method, params) {
	const query = new URLSearchParams(params)
	window.open(`/api/method/${method}?${query.toString()}`, "_blank")
}
