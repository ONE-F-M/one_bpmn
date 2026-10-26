// node --test spiff/src/utils/afterOpeningClick.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { afterOpeningClick } from "./afterOpeningClick.js";

const tick = () => new Promise((resolve) => setTimeout(resolve));

function recordingDirective() {
	const started = [];
	return { started, beforeMount: (el) => started.push(el), unmounted: () => {} };
}

test("the listener starts only after the opening click has finished", async () => {
	const directive = recordingDirective();
	const menu = { isConnected: true };
	afterOpeningClick(directive).mounted(menu, {}, {});
	assert.deepEqual(directive.started, [], "started during the click that opened the menu");
	await tick();
	assert.deepEqual(directive.started, [menu]);
});

test("a menu gone before the click finished never starts listening", async () => {
	const directive = recordingDirective();
	afterOpeningClick(directive).mounted({ isConnected: false }, {}, {});
	await tick();
	assert.deepEqual(directive.started, []);
});
