import { test } from "vitest"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { join } from "node:path"

const here = fileURLToPath(new URL("../../src/components/", import.meta.url))
const css = readFileSync(join(here, "Editor/BpmnEditor/BpmnEditor.css"), "utf8")
	.replace(/\/\*[\s\S]*?\*\//g, "")

const MANDATORY_IDS = [
	"spiffworkflow-assigneeMode",
	"spiffworkflow-assigneeUser",
	"spiffworkflow-assigneeDocfield",
	"spiffworkflow-assigneeUsers",
	"spiffworkflow-assigneeTableField",
	"spiffworkflow-taskActions",
	"spiffworkflow-serverScript",
	"spiffworkflow-notificationName",
	"spiffworkflow-serviceType",
]

// The one rule whose declarations add the " *" after a panel label.
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
const asteriskRule = rules.find(
	([, selectors, body]) =>
		/content:\s*" \*"/.test(body) && selectors.includes(".bio-properties-panel-label::after"),
)

test("the mandatory-field asterisk rule exists and is red", () => {
	assert.ok(asteriskRule, "no rule adds an asterisk after .bio-properties-panel-label")
	assert.match(asteriskRule[2], /color:\s*var\(--red-500,\s*#e53e3e\)/)
})

for (const id of MANDATORY_IDS) {
	test(`${id} is marked with an asterisk on its label`, () => {
		assert.ok(asteriskRule, "asterisk rule missing")
		const selectors = asteriskRule[1].split(",").map((s) => s.trim())
		assert.ok(
			selectors.includes(
				`.bio-properties-panel-entry[data-entry-id="${id}"] .bio-properties-panel-label::after`,
			),
			`${id} is missing from the asterisk rule`,
		)
	})
}

test("the asterisk rule lists exactly the nine mandatory entries", () => {
	assert.ok(asteriskRule, "asterisk rule missing")
	assert.equal(asteriskRule[1].split(",").length, MANDATORY_IDS.length)
})
