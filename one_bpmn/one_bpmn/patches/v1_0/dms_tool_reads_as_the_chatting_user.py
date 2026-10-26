"""The DMS tool script passes the conversation to the search, so reads are checked as the person chatting."""

from one_bpmn.one_bpmn.patches.v1_0.general_chat_answers_from_dms import _upsert_tool_script


def execute():
	_upsert_tool_script()
