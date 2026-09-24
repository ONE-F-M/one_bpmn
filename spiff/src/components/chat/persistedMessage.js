// A reply streams under a temporary id; once saved, ratings must name the Chat Message instead.
export function adoptPersistedName(items, { stream_id: streamId, message_name: messageName }) {
	for (const item of items) {
		if (item.message && item.message === streamId) item.message = messageName;
	}
}
