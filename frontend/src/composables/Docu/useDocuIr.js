import { ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { DOCU_API } from "@/utils/docuApi";
import { FIELD_FLAGS, STRUCTURAL } from "@/utils/docuFieldDefs";
import {
	SETTING_FLAG_KEYS,
	SETTING_INT_KEYS,
	SETTING_STR_KEYS,
	normalizePermission,
} from "@/utils/docuSettingsDefs";

export function useDocuIr({ tree, settings }) {
	const { buildTree, flatten, selectForm } = tree;
	const { dtName, dtModule, dtAutoname, isChild, dtSettings, permissions, sanitizeModule } =
		settings;

	const applyError = ref("");
	const appliedName = ref("");
	const baseModified = ref(""); // the DocType's modified stamp as last read; the server refuses a save over a newer one

	function loadIr(ir) {
		if (!ir) return;
		if (ir.doctype_name) dtName.value = ir.doctype_name;
		dtModule.value = sanitizeModule(ir.module);
		dtAutoname.value = ir.autoname || "";
		isChild.value = !!ir.is_child_table;
		// Only overwrite a setting the IR actually carries - an agent turn returns
		// fields without settings, so session-set settings must survive it.
		for (const k of SETTING_FLAG_KEYS) if (k in ir) dtSettings[k] = !!ir[k];
		for (const k of SETTING_INT_KEYS) if (k in ir) dtSettings[k] = Number(ir[k]) || 0;
		for (const k of SETTING_STR_KEYS) if (k in ir) dtSettings[k] = ir[k] || "";
		// Same rule as settings: a turn that says nothing about permissions leaves
		// the ones on screen alone, so the agent adding a field cannot wipe them.
		if (Array.isArray(ir.permissions))
			permissions.value = ir.permissions.map(normalizePermission);
		buildTree(ir.fields || []);
		selectForm();
		appliedName.value = "";
		applyError.value = "";
	}

	function settingsPayload() {
		const out = {};
		for (const k of SETTING_FLAG_KEYS) out[k] = dtSettings[k] ? 1 : 0;
		for (const k of SETTING_INT_KEYS) out[k] = Number(dtSettings[k]) || 0;
		for (const k of SETTING_STR_KEYS) out[k] = (dtSettings[k] || "").toString().trim();
		return out;
	}

	function currentIr() {
		return {
			doctype_name: dtName.value.trim(),
			module: dtModule.value || "ONE BPMN",
			is_child_table: isChild.value,
			autoname: dtAutoname.value || "",
			...settingsPayload(),
			permissions: permissions.value
				.filter((p) => (p.role || "").trim())
				.map(normalizePermission),
			fields: flatten().map((f) => {
				const out = { ...f }; // preserve all properties, incl. ones the builder doesn't show
				const structural = STRUCTURAL.has(f.fieldtype);
				out.fieldname = structural ? "" : (f.fieldname || "").trim();
				out.label = f.label || "";
				out.options = (f.options || "").trim();
				for (const flag of FIELD_FLAGS) {
					if (flag in out) out[flag] = out[flag] ? 1 : 0;
				}
				return out;
			}),
		};
	}

	async function loadSchema(dt) {
		try {
			const res = await frappeRequest({
				url: `${DOCU_API}get_doctype_schema`,
				params: { doctype: dt },
			});
			if (res?.exists && res.doctype_ir) {
				loadIr(res.doctype_ir);
				baseModified.value = res.modified || "";
			}
		} catch {
			/* new doctype — nothing to load */
		}
	}

	return { applyError, appliedName, baseModified, loadIr, settingsPayload, currentIr, loadSchema };
}
