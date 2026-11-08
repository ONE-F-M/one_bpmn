/**
 * Hides the native bulk Submit, Cancel and Delete items from the list view
 * Actions menu for DocTypes Processa runs. The list comes from boot info
 * (get_processa_controlled_doctypes), so it is known before the menu is built.
 */
(function () {
	"use strict";

	const NATIVE_ACTIONS = ["Submit", "Cancel", "Delete"];
	const LABEL_CONTEXT = "Button in list view actions menu";

	const ListViewProto = frappe.views.ListView.prototype;
	const _original_get_actions_menu_items = ListViewProto.get_actions_menu_items;

	ListViewProto.get_actions_menu_items = function () {
		const items = _original_get_actions_menu_items.call(this);
		if (!(frappe.boot.processa_doctypes || []).includes(this.doctype)) return items;

		const hidden = NATIVE_ACTIONS.map((label) => __(label, null, LABEL_CONTEXT));
		return items.filter((item) => !hidden.includes(item.label));
	};
})();
