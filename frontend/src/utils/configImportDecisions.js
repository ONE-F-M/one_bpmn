// Splits the import dialog's decisions into the script overwrite call and the agent record overwrite call.

export const SCRIPT_TYPE = "Server Script";

export function overwritePayloads(items, decisions) {
	const scripts = [];
	const records = [];
	items.forEach((item, idx) => {
		if (decisions[idx] !== "overwrite") return;
		if (item.type === SCRIPT_TYPE) {
			scripts.push({ name: item.name, script: item.incoming_script });
		} else {
			records.push({ doctype: item.type, name: item.name, data: item.incoming_data });
		}
	});
	return { scripts, records };
}

export function existingText(item) {
	return item.existing_text ?? item.existing_script ?? "";
}

export function incomingText(item) {
	return item.incoming_text ?? item.incoming_script ?? "";
}
