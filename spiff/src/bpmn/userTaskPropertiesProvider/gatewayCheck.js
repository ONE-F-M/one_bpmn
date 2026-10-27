// Gateway check: pure comparison of a User Task's actions against the
// conditions on the outgoing flows of the exclusive gateway that follows it.
// No imports and no DOM, so it runs under `node --test`.

// action == "Name", spaces optional, either quote. Real maps write action == "Approve".
const ACTION_CONDITION = /^\s*action\s*==\s*(?:"([^"]*)"|'([^']*)')\s*$/;
// The same test inside a longer condition, for example action == "Resolve" and doc.resolution_details.
const ACTION_IN_CONDITION = /\baction\s*==\s*(?:"([^"]*)"|'([^']*)')/g;

// Fallback translator: fills {placeholders}. The panel passes the bpmn-js
// translate service, which fills them the same way.
const plain = (template, vars) =>
	template.replace(/\{(\w+)\}/g, (_, key) => (vars ? vars[key] : ""));

/**
 * @param {string[]} actionNames     action names on the task
 * @param {string[]} conditionBodies one condition body per gateway branch, the default branch left out
 * @param {Function} [t]             translate(template, vars)
 * @param {boolean} [hasDefault]     the gateway has a default branch, which takes any other action
 * @returns {{state: "ok" | "bad" | "other", text: string}[]}
 */
export function checkGateway(actionNames, conditionBodies, t = plain, hasDefault = false) {
	const names = (actionNames || []).map((n) => String(n || "").trim()).filter(Boolean);
	const matched = new Set();
	const rows = [];

	(conditionBodies || []).forEach((body) => {
		const exact = ACTION_CONDITION.exec(body || "");
		const found = exact ? [exact] : [...String(body || "").matchAll(ACTION_IN_CONDITION)];
		if (!found.length) {
			rows.push({ state: "other", text: t("Other condition, not checked") });
			return;
		}
		found.forEach((m) => {
			const name = m[1] !== undefined ? m[1] : m[2];
			const condition = `action=="${name}"`;
			if (names.includes(name)) {
				matched.add(name);
				const text = exact ? "{condition} matches action {name}" : "{condition} matches action {name} (and other conditions)";
				rows.push({ state: "ok", text: t(text, { condition, name }) });
			} else {
				rows.push({
					state: "bad",
					text: t("{condition} has no action: add {name} or remove the branch", { condition, name }),
				});
			}
		});
	});

	if (hasDefault) rows.push({ state: "other", text: t("Default branch: takes any action without its own branch") });

	[...new Set(names)].filter((n) => !matched.has(n)).forEach((name) => {
		rows.push(
			hasDefault
				? { state: "other", text: t("Action {name} takes the default branch", { name }) }
				: { state: "bad", text: t("Action {name} has no gateway branch; the task cannot continue on it", { name }) }
		);
	});

	return rows;
}
