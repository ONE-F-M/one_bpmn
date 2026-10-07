// Avatar helpers shared by the presence list (Editor.vue) and comment threads (BpmnEditor.vue).
export function getInitials(fullName) {
	if (!fullName) return "U";
	const names = fullName.trim().split(/\s+/);
	if (names.length === 1) return names[0].charAt(0).toUpperCase();
	return (names[0].charAt(0) + names[names.length - 1].charAt(0)).toUpperCase();
}

const AVATAR_COLORS = [
	"bg-red-500", "bg-orange-500", "bg-amber-500", "bg-yellow-500",
	"bg-lime-500", "bg-green-500", "bg-emerald-500", "bg-teal-500",
	"bg-cyan-500", "bg-sky-500", "bg-blue-500", "bg-indigo-500",
	"bg-violet-500", "bg-purple-500", "bg-fuchsia-500", "bg-pink-500",
	"bg-rose-500",
];

export function getAvatarColor(userName) {
	if (!userName) return "bg-gray-400";
	let hash = 0;
	for (let i = 0; i < userName.length; i++) {
		hash = userName.charCodeAt(i) + ((hash << 5) - hash);
	}
	const colorIndex = Math.abs(hash) % AVATAR_COLORS.length;
	return AVATAR_COLORS[colorIndex];
}
