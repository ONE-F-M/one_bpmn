export const TRANSLATION_FAILED = "Translation did not work. Type the Arabic."
export const TRANSLATE_DELAY_MS = 600

// edited and errors are ref-shaped ({ value }); request(english) resolves to the Arabic.
export function createArabicTranslator({ request, edited, errors, delay = TRANSLATE_DELAY_MS }) {
	const timers = new Map()
	const latest = new Map()

	const isEdited = (field) => edited.value.includes(field)

	function markEdited(field) {
		clearTimeout(timers.get(field))
		if (!isEdited(field)) edited.value = [...edited.value, field]
	}

	function queue(field, english, fill) {
		if (isEdited(field)) return
		clearTimeout(timers.get(field))
		timers.set(field, setTimeout(() => run(field, english, fill), delay))
	}

	function translateAgain(field, english, fill) {
		clearTimeout(timers.get(field))
		edited.value = edited.value.filter((f) => f !== field)
		return run(field, english, fill)
	}

	async function run(field, english, fill) {
		const seq = (latest.get(field) || 0) + 1
		latest.set(field, seq)
		try {
			const arabic = await request(english)
			if (latest.get(field) !== seq || isEdited(field)) return
			setError(field, "")
			fill(arabic)
		} catch {
			if (latest.get(field) === seq) setError(field, TRANSLATION_FAILED)
		}
	}

	function setError(field, message) {
		const { [field]: _old, ...rest } = errors.value
		errors.value = message ? { ...rest, [field]: message } : rest
	}

	return { queue, translateAgain, markEdited, isEdited }
}
