import frappe

from one_bpmn.utils.translation import translate_for_editor


@frappe.whitelist(methods=["POST"])
def translate(text: str, process_model: str = "") -> str:
	"""Arabic for the modeler's English field; needs write on the model, or create when unsaved."""
	return translate_for_editor(text, process_model)
