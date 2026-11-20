import { frappeRequest } from "frappe-ui";

// One Logix check against the saved script, on its Process and script task so an approval counts.
export async function useLogixTestRun({ scriptName, inputs, processContext }) {
	try {
		const result = await frappeRequest({
			url: "/api/method/processa.api.server_scripts.run_logix_test_case",
			method: "POST",
			params: {
				script_name: scriptName,
				inputs: JSON.stringify(inputs || {}),
				process: processContext?.process || "",
				script_task: processContext?.element_id || "",
			},
		});
		return {
			passed: result?.passed ?? false,
			summary: result?.summary || (result?.passed ? "Test passed." : "Test failed."),
		};
	} catch {
		return { passed: false, summary: "Could not run the test - network error." };
	}
}
