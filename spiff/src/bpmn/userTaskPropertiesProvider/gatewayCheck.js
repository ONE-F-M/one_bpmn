// Gateway check: pure comparison of a User Task's actions against the
// conditions on the outgoing flows of the exclusive gateway that follows it.
// No imports and no DOM, so it runs under `node --test`.

// action == "Name", spaces optional, either quote. Real maps write action == "Approve".
const ACTION_CONDITION = /^\s*action\s*==\s*(?:"([^"]*)"|'([^']*)')\s*$/;

// Fallback translator: fills {placeholders}. The panel passes the bpmn-js
// translate service, which fills them the same way.
const plain = (template, vars) =>
	template.replace(/\{(\w+)\}/g, (_, key) => (vars ? vars[key] : ""));

/**
 * @param {string[]} actionNames     action names on the task
 * @param {string[]} conditionBodies one condition body per gateway branch
 * @param {Function} [t]             translate(template, vars)
 * @returns {{state: "ok" | "bad" | "other", text: string}[]}
 */
export function checkGateway(actionNames, conditionBodies, t = plain) {
	const names = (actionNames || []).map((n) => String(n || "").trim()).filter(Boolean);
	const matched = new Set();
	const rows = [];

	(conditionBodies || []).forEach((body) => {
		const m = ACTION_CONDITION.exec(body || "");
		if (!m) {
			rows.push({ state: "other", text: t("Other condition, not checked") });
			return;
		}
		const name = m[1] !== undefined ? m[1] : m[2];
		const condition = `action=="${name}"`;
		if (names.includes(name)) {
			matched.add(name);
			rows.push({ state: "ok", text: t("{condition} matches action {name}", { condition, name }) });
		} else {
			rows.push({
				state: "bad",
				text: t("{condition} has no action: add {name} or remove the branch", { condition, name }),
			});
		}
	});

	[...new Set(names)].filter((n) => !matched.has(n)).forEach((name) => {
		rows.push({
			state: "bad",
			text: t("Action {name} has no gateway branch; the task cannot continue on it", { name }),
		});
	});

	return rows;
}
