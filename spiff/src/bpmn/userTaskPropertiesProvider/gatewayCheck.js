// Gateway check: pure comparison of a User Task's actions against the
// conditions on the outgoing flows of the exclusive gateway that tests them.
// No imports and no DOM, so it runs under `node --test`.

// action == "Name", spaces optional, either quote. Real maps write action == "Approve".
const ACTION_CONDITION = /^\s*action\s*==\s*(?:"([^"]*)"|'([^']*)')\s*$/;
// The same test inside a longer condition, for example action == "Resolve" and doc.resolution_details.
const ACTION_IN_CONDITION = /\baction\s*==\s*(?:"([^"]*)"|'([^']*)')/g;

// How many gateways past the first one the search follows to find the action test.
const MAX_GATEWAY_HOPS = 3;

/** Condition bodies of a gateway's branches, the default branch left out. */
export function branchBodies(gateway) {
	return (gateway.outgoing || [])
		.filter((flow) => flow !== gateway.default)
		.map((flow) => (flow.conditionExpression && flow.conditionExpression.body) || "");
}

function testsAction(gateway) {
	return branchBodies(gateway).some((body) => new RegExp(ACTION_IN_CONDITION.source).test(body));
}

/**
 * The exclusive gateway whose branches test the task's action. When the first gateway tests none,
 * follows its branches straight into further exclusive gateways, up to MAX_GATEWAY_HOPS deep.
 * Returns { gateway, via }: via is the first gateway when the search moved past it, else null.
 */
export function findActionGateway(first) {
	const seen = new Set([first]);
	let level = [first];
	for (let hop = 0; hop <= MAX_GATEWAY_HOPS && level.length; hop++) {
		const hit = level.find(testsAction);
		if (hit) return { gateway: hit, via: hit === first ? null : first };
		level = level
			.flatMap((gateway) => (gateway.outgoing || []).map((flow) => flow.targetRef))
			.filter((target) => target && target.$type === "bpmn:ExclusiveGateway" && !seen.has(target));
		level.forEach((gateway) => seen.add(gateway));
	}
	return { gateway: first, via: null };
}

const MAX_CONDITION_LENGTH = 80;

/** A longer condition on one line, cut to MAX_CONDITION_LENGTH so two branches on one action read apart. */
function shorten(body) {
	const line = String(body).replace(/\s+/g, " ").trim();
	return line.length > MAX_CONDITION_LENGTH ? `${line.slice(0, MAX_CONDITION_LENGTH - 3)}...` : line;
}

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
			const condition = exact ? `action=="${name}"` : shorten(body);
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
