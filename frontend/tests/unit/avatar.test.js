import { test } from "vitest";
import assert from "node:assert/strict";
import {
	getInitials,
	getAvatarColor,
	getCommentInitials,
	getCommentAvatarColor,
} from "../../src/utils/avatar.js";

test("presence initials use the first and last word", () => {
	assert.equal(getInitials("Sam Kumar Ali"), "SA");
	assert.equal(getInitials("  sam   ali "), "SA");
	assert.equal(getInitials("Sam"), "S");
	assert.equal(getInitials(""), "U");
});

test("comment initials use the first two words", () => {
	assert.equal(getCommentInitials("Sam Kumar Ali"), "SK");
	assert.equal(getCommentInitials("Samdani Shariff"), "SS");
	assert.equal(getCommentInitials(""), "??");
});

const NAMES = ["Administrator", "a@b.c", "Samdani Shariff", "Sam Kumar Ali", "x", "zz@one-fm.com"];

// Verbatim originals from Process.vue and BpmnEditor.vue before the move.
function originalPresenceColor(userName) {
	const colors = [
		"bg-red-500",
		"bg-orange-500",
		"bg-amber-500",
		"bg-yellow-500",
		"bg-lime-500",
		"bg-green-500",
		"bg-emerald-500",
		"bg-teal-500",
		"bg-cyan-500",
		"bg-sky-500",
		"bg-blue-500",
		"bg-indigo-500",
		"bg-violet-500",
		"bg-purple-500",
		"bg-fuchsia-500",
		"bg-pink-500",
		"bg-rose-500",
	];
	if (!userName) return "bg-gray-400";
	let hash = 0;
	for (let i = 0; i < userName.length; i++) {
		hash = userName.charCodeAt(i) + ((hash << 5) - hash);
	}
	return colors[Math.abs(hash) % colors.length];
}

function originalCommentColor(userName) {
	const colors = [
		"bg-red-500",
		"bg-blue-500",
		"bg-green-500",
		"bg-yellow-500",
		"bg-purple-500",
		"bg-pink-500",
		"bg-indigo-500",
		"bg-teal-500",
		"bg-orange-500",
		"bg-cyan-500",
	];
	let hash = 0;
	for (let i = 0; i < (userName || "").length; i++) {
		hash = (userName || "").charCodeAt(i) + ((hash << 5) - hash);
	}
	return colors[Math.abs(hash) % colors.length];
}

test("presence colour matches the original and falls back to grey", () => {
	assert.equal(getAvatarColor(""), "bg-gray-400");
	for (const n of NAMES) assert.equal(getAvatarColor(n), originalPresenceColor(n));
});

test("comment colour matches the original for any name, including none", () => {
	assert.equal(getCommentAvatarColor(undefined), originalCommentColor(undefined));
	for (const n of NAMES) assert.equal(getCommentAvatarColor(n), originalCommentColor(n));
});
