// What an AI task still needs before it can run, or null once it is configured.
export function missingAiTaskSetting({ aiAgentConfig, aiModel }) {
	if (!aiAgentConfig) return "agent_config"
	if (!String(aiModel || "").trim()) return "model"
	return null
}
