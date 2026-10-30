# Custom field imports
from one_bpmn.one_bpmn.custom.custom_field.comment import get_comment_custom_fields


def get_custom_fields():
	"""ONE BPMN specific custom fields that need to be added to standard DocTypes."""
	custom_fields = get_comment_custom_fields()
	return custom_fields
