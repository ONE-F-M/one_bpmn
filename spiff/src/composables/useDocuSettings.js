import { computed, reactive, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { DOCU_API } from "@/utils/docuApi";
import {
	buildSettingsSections,
	defaultSettings,
	normalizePermission,
} from "@/utils/docuSettingsDefs";

export function useDocuSettings({ doctype, onChange }) {
	const dtName = ref(doctype || "");
	const dtModule = ref("ONE BPMN");
	const dtAutoname = ref("");
	const isChild = ref(false);
	const modules = ref([]); // Module Def names for the module picker

	const dtSettings = reactive(defaultSettings());
	const permissions = ref([]);
	const roles = ref([]);

	// Keep a role the agent named selectable even before the list arrives, and even
	// if it is disabled - dropping it silently would look like the rule was ignored.
	function roleOptions(current) {
		const list = roles.value.slice();
		if (current && !list.includes(current)) list.unshift(current);
		return list;
	}

	function addPermission() {
		// A new rule starts as plain read access, the least it can grant.
		permissions.value.push(normalizePermission({ read: 1 }));
		onChange();
	}

	function removePermission(index) {
		permissions.value.splice(index, 1);
		onChange();
	}

	// Always include the current module (e.g. an agent-supplied one) so it stays selectable.
	const moduleOptions = computed(() => {
		const list = modules.value.slice();
		for (const m of [dtModule.value, "ONE BPMN"]) {
			if (m && !list.includes(m)) list.unshift(m);
		}
		return list;
	});

	const settingsSections = computed(() => buildSettingsSections(isChild.value));

	// An IR module is accepted only when it names a real Module Def. The match is
	// case-insensitive and is normalised to the Module Def's own spelling.
	function sanitizeModule(m) {
		if (!m) return dtModule.value || "ONE BPMN";
		if (!modules.value.length) return m;
		const match = modules.value.find(
			(known) => String(known).toLowerCase() === String(m).toLowerCase(),
		);
		if (match) return match;
		// Genuinely not a module. Falling back is right, but say so - a silent
		// substitution is how this went unnoticed for so long.
		console.warn(
			`Docu: "${m}" is not a Frappe module; keeping ${dtModule.value || "ONE BPMN"}.`,
		);
		return dtModule.value || "ONE BPMN";
	}

	async function loadRoles() {
		try {
			const res = await frappeRequest({ url: `${DOCU_API}list_roles` });
			if (Array.isArray(res)) roles.value = res;
		} catch {
			/* the rule keeps whatever role it already names */
		}
	}

	async function loadModules() {
		try {
			const res = await frappeRequest({ url: `${DOCU_API}list_modules` });
			if (Array.isArray(res)) {
				modules.value = res;
				// Normalise a module set before the list loaded; replace only what does not match.
				if (dtModule.value) dtModule.value = sanitizeModule(dtModule.value);
			}
		} catch {
			/* fall back to the current module only */
		}
	}

	return {
		dtName,
		dtModule,
		dtAutoname,
		isChild,
		modules,
		dtSettings,
		permissions,
		roles,
		roleOptions,
		addPermission,
		removePermission,
		moduleOptions,
		settingsSections,
		sanitizeModule,
		loadRoles,
		loadModules,
	};
}
