// Cancel on a DocType with a cancellation map starts that map; the server cancels only when the map approves.
(() => {
	const hasCancellationMap = (doctype) =>
		(frappe.boot.processa_cancellation_doctypes || []).includes(doctype);

	const FormProto = frappe.ui.form.Form.prototype;
	const nativeSavecancel = FormProto.savecancel;

	FormProto.savecancel = function (btn, callback, onError) {
		if (!hasCancellationMap(this.doctype)) {
			return nativeSavecancel.call(this, btn, callback, onError);
		}
		this.validate_form_action("Cancel");
		frappe.confirm(
			__("Cancelling {0} {1} needs approval. Start the cancellation process?", [
				__(this.doctype),
				this.docname,
			]),
			async () => {
				try {
					await frappe.xcall("one_bpmn.api.instances.request_cancellation", {
						doctype: this.doctype,
						docname: this.docname,
					});
					await this.reload_doc();
				} catch (error) {
					if (onError) onError(error);
				}
			}
		);
	};

	$(document).on("form-refresh", (event, frm) => {
		const pending = frm.doc.__onload && frm.doc.__onload.pending_cancellation;
		if (pending) {
			frm.set_intro(__("Cancellation requested. Waiting for approval in process {0}.", [pending]), "orange");
		}
	});
})();
