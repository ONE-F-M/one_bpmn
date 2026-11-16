const PRESENCE_COLORS = [
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

const COMMENT_COLORS = [
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

function hashName(name) {
	let hash = 0;
	for (let i = 0; i < name.length; i++) {
		hash = name.charCodeAt(i) + ((hash << 5) - hash);
	}
	return Math.abs(hash);
}

// Presence avatars in the process header: first and last word, 17 colours.
export function getInitials(fullName) {
	if (!fullName) return "U";
	const names = fullName.trim().split(/\s+/);
	if (names.length === 1) return names[0].charAt(0).toUpperCase();
	return (names[0].charAt(0) + names[names.length - 1].charAt(0)).toUpperCase();
}

export function getAvatarColor(userName) {
	if (!userName) return "bg-gray-400";
	return PRESENCE_COLORS[hashName(userName) % PRESENCE_COLORS.length];
}

// Comment-list avatars: first two words, 10 colours.
export function getCommentInitials(fullName) {
	if (!fullName) return "??";
	return fullName
		.split(" ")
		.map((n) => n[0])
		.join("")
		.toUpperCase()
		.substring(0, 2);
}

export function getCommentAvatarColor(userName) {
	return COMMENT_COLORS[hashName(userName || "") % COMMENT_COLORS.length];
}
