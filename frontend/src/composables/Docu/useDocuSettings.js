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
	const dtApp = ref("");
	const dtModule = ref("");
	const dtAutoname = ref("");
	const isChild = ref(false);
	const apps = ref([]); // installed apps that own modules, for the app picker
	const modules = ref([]); // { name, app } for every Module Def

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

	// Only the picked app's modules, so a DocType cannot land in another app's module.
	const moduleOptions = computed(() =>
		modules.value.filter((m) => m.app === dtApp.value).map((m) => m.name),
	);

	// Switching app drops a module that belongs to the old one.
	function pickApp(app) {
		dtApp.value = app;
		if (modules.value.find((m) => m.name === dtModule.value)?.app !== app) dtModule.value = "";
		onChange();
	}

	const settingsSections = computed(() => buildSettingsSections(isChild.value));

	// An IR module is accepted only when it names a real Module Def inside the picked app,
	// matched case-insensitively and normalised to the Module Def's own spelling.
	function sanitizeModule(m) {
		if (!m) return dtModule.value;
		if (!modules.value.length) return m;
		const match = modules.value.find(
			(known) => known.name.toLowerCase() === String(m).toLowerCase(),
		);
		if (!match || (dtApp.value && match.app !== dtApp.value)) return dtModule.value;
		return match.name;
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
			const [appList, moduleList] = await Promise.all([
				frappeRequest({ url: `${DOCU_API}list_apps` }),
				frappeRequest({ url: `${DOCU_API}list_modules` }),
			]);
			if (Array.isArray(appList)) apps.value = appList;
			if (Array.isArray(moduleList)) {
				modules.value = moduleList;
				// Normalise a module set before the list loaded.
				if (dtModule.value) dtModule.value = sanitizeModule(dtModule.value);
			}
		} catch {
			/* the pickers stay empty and the server keeps asking for an app and module */
		}
	}

	return {
		dtName,
		dtApp,
		dtModule,
		apps,
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
		pickApp,
		settingsSections,
		sanitizeModule,
		loadRoles,
		loadModules,
	};
}
