// composables/useNotificationDialog.js
// Extracted from Editor.vue to reduce coupling (Review Comment #1)

import { ref, computed } from "vue";
import { frappeRequest } from "frappe-ui";

// Monotonically increasing row ID for stable :key bindings (Review Comment #2)
let _rowIdCounter = 0;

function makeEmptyNotif() {
	return {
		name: "", channel: "", event: "", document_type: "", subject: "",
		condition: "", message: "", message_type: "Markdown", module: "",
		sender: "", sender_email: "", attach_print: false, print_format: "",
		send_system_notification: false, slack_webhook_url: "", twilio_number: "",
		method: "", date_changed: "", days_in_advance: 0, value_changed: "",
		send_to_all_assignees: false, recipients: [],
		set_property_after_alert: "", property_value: "",
	};
}

export function useNotificationDialog(doctypeOptions, moduleOptions, showToast) {
	// Dialog visibility & mode
	const showNotificationDialog = ref(false);
	const notifDialogMode = ref("select");

	// Select Existing state
	const notifications = ref([]);
	const notifSearch = ref("");
	const notifDoctypeFilter = ref("");
	const showNotifDoctypeDropdown = ref(false);
	const selectedNotification = ref(null);
	const loadingNotifications = ref(false);

	// Create New state
	const creatingNotification = ref(false);
	const notifNewDoctypeSearch = ref("");
	const showNotifNewDoctypeDropdown = ref(false);
	const notifModuleSearch = ref("");
	const showNotifModuleDropdown = ref(false);
	const newNotif = ref(makeEmptyNotif());

	// Plain variable — NOT reactive (bpmn-js elements have frozen properties)
	let activeNotificationEvent = null;

	const notifEvents = [
		"New", "Save", "Submit", "Cancel", "Days After", "Days Before",
		"Value Change", "Method", "Custom",
	];

	// --- Computed filters ---

	const filteredNotifications = computed(() => {
		let list = notifications.value;
		if (notifDoctypeFilter.value) {
			list = list.filter((n) => n.document_type === notifDoctypeFilter.value);
		}
		if (notifSearch.value) {
			const q = notifSearch.value.toLowerCase();
			list = list.filter(
				(n) =>
					n.name.toLowerCase().includes(q) ||
					(n.subject && n.subject.toLowerCase().includes(q)) ||
					(n.channel && n.channel.toLowerCase().includes(q)) ||
					(n.document_type && n.document_type.toLowerCase().includes(q))
			);
		}
		return list;
	});

	const filteredNotifDoctypeOptions = computed(() => {
		if (!notifDoctypeFilter.value) return doctypeOptions.value.slice(0, 50);
		const q = notifDoctypeFilter.value.toLowerCase();
		return doctypeOptions.value.filter((dt) => dt.toLowerCase().includes(q)).slice(0, 50);
	});

	const filteredNotifNewDoctypeOptions = computed(() => {
		if (!notifNewDoctypeSearch.value) return doctypeOptions.value.slice(0, 50);
		const q = notifNewDoctypeSearch.value.toLowerCase();
		return doctypeOptions.value.filter((dt) => dt.toLowerCase().includes(q)).slice(0, 50);
	});

	const filteredNotifModuleOptions = computed(() => {
		if (!notifModuleSearch.value) return moduleOptions.value.slice(0, 50);
		const q = notifModuleSearch.value.toLowerCase();
		return moduleOptions.value.filter((m) => m.toLowerCase().includes(q)).slice(0, 50);
	});

	// --- Helpers ---

	function channelIcon(channel) {
		const icons = {
			Email: "📧",
			WhatsApp: "💬",
			"System Notification": "🔔",
			SMS: "📱",
			Slack: "🔗",
		};
		return icons[channel] || "📋";
	}

	function addRecipientRow() {
		newNotif.value.recipients.push({
			_id: ++_rowIdCounter, // stable key (Review Comment #2)
			receiver_by_document_field: "",
			receiver_by_role: "",
			cc: "",
			bcc: "",
			condition: "",
		});
	}

	function removeRecipientRow(idx) {
		newNotif.value.recipients.splice(idx, 1);
	}

	// --- Handlers ---

	async function openDialog(event) {
		activeNotificationEvent = event;

		// Reset
		notifDialogMode.value = "select";
		notifSearch.value = "";
		notifDoctypeFilter.value = "";
		showNotifDoctypeDropdown.value = false;
		selectedNotification.value = event.notificationName || null;
		notifNewDoctypeSearch.value = "";
		showNotifNewDoctypeDropdown.value = false;
		notifModuleSearch.value = "";
		showNotifModuleDropdown.value = false;
		newNotif.value = makeEmptyNotif();

		// Fetch notifications
		loadingNotifications.value = true;
		showNotificationDialog.value = true;

		try {
			const response = await fetch(
				'/api/resource/Notification?fields=["name","subject","channel","document_type","enabled","event","modified"]&limit_page_length=0&order_by=modified%20desc',
				{ headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" } }
			);
			const json = await response.json();
			notifications.value = Array.isArray(json.data) ? json.data : [];
		} catch (error) {
			console.error("Failed to load notifications:", error);
			notifications.value = [];
		} finally {
			loadingNotifications.value = false;
		}

		// Fetch DocTypes and Modules (reuse cached)
		if (doctypeOptions.value.length === 0) {
			try {
				const dtResp = await frappeRequest({
					url: "/api/method/frappe.client.get_list",
					params: { doctype: "DocType", fields: ["name"], limit_page_length: 0, order_by: "name asc" },
				});
				doctypeOptions.value = (dtResp.message || dtResp || []).map((d) => d.name);
			} catch (e) {
				console.error("Failed to load DocTypes:", e);
			}
		}
		if (moduleOptions.value.length === 0) {
			try {
				const modResp = await frappeRequest({
					url: "/api/method/frappe.client.get_list",
					params: { doctype: "Module Def", fields: ["name"], limit_page_length: 0, order_by: "name asc" },
				});
				moduleOptions.value = (modResp.message || modResp || []).map((m) => m.name);
			} catch (e) {
				console.error("Failed to load Modules:", e);
			}
		}
	}

	function linkNotification() {
		if (activeNotificationEvent && activeNotificationEvent.eventBus && selectedNotification.value) {
			activeNotificationEvent.eventBus.fire("spiff.notification.update", {
				element: activeNotificationEvent.element,
				notificationName: selectedNotification.value,
			});
		}
		showNotificationDialog.value = false;
		activeNotificationEvent = null;
	}

	async function createAndLinkNotification() {
		if (!newNotif.value.name || !newNotif.value.channel || !newNotif.value.document_type) {
			showToast("Validation", "Name, channel, and document type are required.", "red");
			return;
		}

		creatingNotification.value = true;
		try {
			const result = await frappeRequest({
				url: "one_bpmn.api.create_notification",
				params: {
					notification_name: newNotif.value.name,
					channel: newNotif.value.channel,
					document_type: newNotif.value.document_type,
					event: newNotif.value.event || "New",
					...(newNotif.value.subject && { subject: newNotif.value.subject }),
					...(newNotif.value.message && { message: newNotif.value.message }),
					...(newNotif.value.message_type && { message_type: newNotif.value.message_type }),
					...(newNotif.value.condition && { condition: newNotif.value.condition }),
					...(newNotif.value.module && { module: newNotif.value.module }),
					...(newNotif.value.sender && { sender: newNotif.value.sender }),
					...(newNotif.value.sender_email && { sender_email: newNotif.value.sender_email }),
					...(newNotif.value.attach_print && { attach_print: 1 }),
					...(newNotif.value.print_format && { print_format: newNotif.value.print_format }),
					...(newNotif.value.send_system_notification && { send_system_notification: 1 }),
					...(newNotif.value.slack_webhook_url && { slack_webhook_url: newNotif.value.slack_webhook_url }),
					...(newNotif.value.twilio_number && { twilio_number: newNotif.value.twilio_number }),
					...(newNotif.value.method && { method: newNotif.value.method }),
					...(newNotif.value.date_changed && { date_changed: newNotif.value.date_changed }),
					...(newNotif.value.days_in_advance && { days_in_advance: newNotif.value.days_in_advance }),
					...(newNotif.value.value_changed && { value_changed: newNotif.value.value_changed }),
					...(newNotif.value.send_to_all_assignees && { send_to_all_assignees: 1 }),
					...(newNotif.value.recipients.length > 0 && {
						recipients: JSON.stringify(newNotif.value.recipients),
					}),
					...(newNotif.value.set_property_after_alert && { set_property_after_alert: newNotif.value.set_property_after_alert }),
					...(newNotif.value.property_value && { property_value: newNotif.value.property_value }),
				},
			});

			if (activeNotificationEvent && activeNotificationEvent.eventBus) {
				activeNotificationEvent.eventBus.fire("spiff.notification.update", {
					element: activeNotificationEvent.element,
					notificationName: result.name,
				});
			}

			showToast("Success", `Notification "${result.name}" created and linked.`, "green");
			showNotificationDialog.value = false;
			activeNotificationEvent = null;
		} catch (error) {
			console.error("Failed to create notification:", error);
			showToast("Error", "Failed to create: " + (error.message || error), "red");
		} finally {
			creatingNotification.value = false;
		}
	}

	return {
		// State
		showNotificationDialog,
		notifDialogMode,
		notifications,
		notifSearch,
		notifDoctypeFilter,
		showNotifDoctypeDropdown,
		selectedNotification,
		loadingNotifications,
		creatingNotification,
		notifNewDoctypeSearch,
		showNotifNewDoctypeDropdown,
		notifModuleSearch,
		showNotifModuleDropdown,
		newNotif,
		notifEvents,
		// Computed
		filteredNotifications,
		filteredNotifDoctypeOptions,
		filteredNotifNewDoctypeOptions,
		filteredNotifModuleOptions,
		// Methods
		channelIcon,
		addRecipientRow,
		removeRecipientRow,
		openDialog,
		linkNotification,
		createAndLinkNotification,
	};
}
