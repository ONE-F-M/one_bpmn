// node --test spiff/src/utils/arabicTranslation.test.mjs

import { test, mock } from "node:test"
import assert from "node:assert/strict"

import { TRANSLATION_FAILED, createArabicTranslator } from "./arabicTranslation.js"

function setup(request, edited = []) {
	const state = { edited: { value: edited }, errors: { value: {} }, filled: [] }
	const translator = createArabicTranslator({ request, edited: state.edited, errors: state.errors })
	const fill = (arabic) => state.filled.push(arabic)
	return { ...state, translator, fill }
}

const flush = () => new Promise((resolve) => setImmediate(resolve))

test("only the last English after a 600 ms pause is translated", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] })
	const request = mock.fn(async (text) => `ar:${text}`)
	const { translator, fill, filled } = setup(request)

	translator.queue("subject", "Lea", fill)
	t.mock.timers.tick(300)
	translator.queue("subject", "Leave", fill)
	t.mock.timers.tick(599)
	assert.equal(request.mock.callCount(), 0)
	t.mock.timers.tick(1)
	await flush()

	assert.equal(request.mock.callCount(), 1)
	assert.deepEqual(filled, ["ar:Leave"])
})

test("a hand-edited field is left alone until Translate again", async (t) => {
	t.mock.timers.enable({ apis: ["setTimeout"] })
	const request = mock.fn(async (text) => `ar:${text}`)
	const { translator, fill, filled, edited } = setup(request)

	translator.markEdited("subject")
	translator.queue("subject", "Leave", fill)
	t.mock.timers.tick(600)
	await flush()
	assert.equal(request.mock.callCount(), 0)
	assert.equal(translator.isEdited("subject"), true)

	await translator.translateAgain("subject", "Leave", fill)
	assert.deepEqual(edited.value, [])
	assert.deepEqual(filled, ["ar:Leave"])
})

test("typing Arabic while a translation is in flight keeps the typed text", async () => {
	let resolve
	const { translator, fill, filled } = setup(() => new Promise((r) => (resolve = r)))

	const pending = translator.translateAgain("subject", "Leave", fill)
	translator.markEdited("subject")
	resolve("ar:Leave")
	await pending
	assert.deepEqual(filled, [])
})

test("an endpoint error keeps the Arabic and shows the message for that field", async () => {
	const { translator, fill, filled, errors } = setup(async () => {
		throw new Error("429")
	})

	await translator.translateAgain("subject", "Leave", fill)
	assert.deepEqual(filled, [])
	assert.deepEqual(errors.value, { subject: TRANSLATION_FAILED })
})

test("a later success clears the field's error", async () => {
	let fail = true
	const { translator, fill, errors } = setup(async (text) => {
		if (fail) throw new Error("timeout")
		return `ar:${text}`
	})

	await translator.translateAgain("subject", "Leave", fill)
	fail = false
	await translator.translateAgain("subject", "Leave", fill)
	assert.deepEqual(errors.value, {})
})

test("an older response that lands last is dropped", async () => {
	const resolvers = []
	const { translator, fill, filled } = setup(() => new Promise((r) => resolvers.push(r)))

	const first = translator.translateAgain("subject", "Lea", fill)
	const second = translator.translateAgain("subject", "Leave", fill)
	resolvers[1]("ar:Leave")
	resolvers[0]("ar:Lea")
	await Promise.all([first, second])
	assert.deepEqual(filled, ["ar:Leave"])
})
