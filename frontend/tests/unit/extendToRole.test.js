import { test } from "vitest"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

const src = (path) => readFileSync(fileURLToPath(new URL(`../../src/${path}`, import.meta.url)), "utf8")
const props = src("bpmn/userTaskPropertiesProvider/UserTaskProps.js")
const moddle = src("utils/editorModdleExtensions.js")

test("the user task carries an extendToRole attribute the editor can store", () => {
	assert.match(moddle, /\{ name: "extendToRole", isAttr: true, type: "String" \}/)
})

test("the properties panel offers Extend to Role as a multi-select of roles on every user task", () => {
	const entries = props.slice(props.indexOf("export function UserTaskProps"), props.indexOf("return entries;"))
	assert.match(entries, /id: "spiffworkflow-extendToRole"/)
	const component = props.slice(props.indexOf("function ExtendToRoleComponent"))
	assert.match(component, /multiple: true/)
	assert.match(component, /fetchApi: fetchRoles/)
	assert.match(src("bpmn/shared/fetchRoles.js"), /doctype: "Role"/)
	assert.match(component, /"spiffworkflow:extendToRole": val \|\| undefined/)
	assert.match(component, /translate\("Extend to Role"\)/)
})
