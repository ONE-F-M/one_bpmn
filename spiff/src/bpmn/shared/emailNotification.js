/**
 * The Email Notification service task attributes the editor dialog reads and writes,
 * the Save check, and the panel summary. Pure, so node --test covers it.
 */
export const EMAIL_EDITOR_ATTRS = [
	"emailAccount",
	"emailUseDoctype",
	"emailDoctype",
	"emailSubject",
	"emailTo",
	"emailToDocFields",
	"emailToTableField",
	"emailToTableUserField",
	"emailToRoles",
	"emailCc",
	"emailBcc",
	"emailBody",
	"emailLayout",
	"emailSubjectAr",
	"emailHeadingEn",
	"emailHeadingAr",
	"emailMessageEn",
	"emailMessageAr",
	"emailShowStatus",
	"emailFacts",
	"emailDetails",
	"emailAttachments",
	"emailArabicEdited",
];

/** "html" sends the Email Body as today, "notice" the Notice layout; empty follows whether a body exists. */
export function emailLayout(values) {
	return values.emailLayout || (filled(values.emailBody) ? "html" : "notice");
}

export const EMAIL_ERRORS = {
	emailAccount: "Pick the account the email is sent from. Deploy rejects an Email Notification with no account.",
	recipients: "Add at least one recipient: an address, a document field, a table field or a role.",
	emailSubject: "Write a subject.",
};

// the tab each error opens, in the order Save checks them
const ERROR_TABS = [
	["emailAccount", "sending"],
	["recipients", "recipients"],
	["emailSubject", "content"],
];

const filled = (value) => !!String(value || "").trim();

/** Comma-separated values as a list, blanks dropped. */
export function splitList(raw) {
	return String(raw || "")
		.split(",")
		.map((v) => v.trim())
		.filter(Boolean);
}

export function hasRecipient(values) {
	return ["emailTo", "emailToDocFields", "emailToTableField", "emailToRoles"].some((name) => filled(values[name]));
}

/** errors keyed by field, and the failing tabs in the order Sending, Recipients, Content. */
export function validateEmailNotification(values) {
	const failing = {
		emailAccount: !filled(values.emailAccount),
		recipients: !hasRecipient(values),
		emailSubject: !filled(values.emailSubject),
	};
	const errors = Object.fromEntries(
		Object.entries(failing)
			.filter(([, fails]) => fails)
			.map(([key]) => [key, EMAIL_ERRORS[key]])
	);
	const tabs = ERROR_TABS.filter(([key]) => failing[key]).map(([, tab]) => tab);
	return { errors, tabs };
}

/** The attribute names whose value differs between the saved values and the edited copy. */
export function changedAttrs(saved, edited) {
	return EMAIL_EDITOR_ATTRS.filter((name) => (saved[name] || "") !== (edited[name] || ""));
}

/** Rows under Launch Editor; fieldLabels maps fieldname to label for the task's DocType. */
export function emailSummary(values, fieldLabels = {}) {
	const label = (fieldname) => fieldLabels[fieldname] || fieldname;
	const facts = (values.emailFacts ? JSON.parse(values.emailFacts) : []).map((entry) =>
		label(Array.isArray(entry) ? entry[0] : entry)
	);
	const recipients = [
		...splitList(values.emailToDocFields).map(label),
		...(filled(values.emailToTableField) ? [label(values.emailToTableField)] : []),
		...splitList(values.emailToRoles).map((role) => `${role} role`),
		...splitList(values.emailTo),
	];
	const cc = splitList(values.emailCc).length;
	const bcc = splitList(values.emailBcc).length;
	const copies = [cc && `CC ${cc}`, bcc && `BCC ${bcc}`].filter(Boolean).join(" · ");
	const useDoctype = values.emailUseDoctype === "true";

	return {
		rows: [
			{ k: "Layout", v: emailLayout(values) === "html" ? "Custom HTML" : "Notice" },
			{ k: "Email Account", v: values.emailAccount || "Not set · required", warn: !filled(values.emailAccount) },
			{ k: "DocType", v: useDoctype ? values.emailDoctype || "Not set" : "Not based on a record" },
			{ k: "Recipients", v: recipients.join(", ") || "None · required", warn: !recipients.length },
			{ k: "CC / BCC", v: copies || "None" },
			{ k: "Subject", v: values.emailSubject || "Not set · required", warn: !filled(values.emailSubject) },
			...(emailLayout(values) === "notice" ? [{ k: "Key facts", v: facts.join(", ") || "None" }] : []),
		],
		configured: !Object.keys(validateEmailNotification(values).errors).length,
	};
}
