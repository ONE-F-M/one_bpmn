"""A conversation with an agent is private to the person who had it.

Both chat doctypes granted the role ``All`` read, write, create and delete, so
any signed-in employee could list every conversation on the site and read what
anyone had said to an agent.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_chat_privacy
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.chat_permissions import chat_message_has_permission, is_participant

OWNER = "wi2364_owner@example.com"
OUTSIDER = "wi2364_outsider@example.com"
GUEST_OF = "wi2364_guest@example.com"


def _user(email: str, roles=()):
	if not frappe.db.exists("User", email):
		doc = frappe.new_doc("User")
		doc.email = email
		doc.first_name = email.split("@")[0]
		doc.send_welcome_email = 0
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	doc = frappe.get_doc("User", email)
	for role in roles:
		if role not in [r.role for r in doc.roles]:
			doc.append("roles", {"role": role})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return email


class ChatPrivacyCase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_user(OWNER)
		_user(OUTSIDER)
		_user(GUEST_OF)
		self._made = []

		frappe.set_user(OWNER)
		conv = frappe.new_doc("Chat Conversation")
		conv.agent_mode = "ProsAlly"
		conv.title = "Unreleased process"
		conv.append("participants", {"user": GUEST_OF})
		conv.insert()
		self.conv = conv.name
		self._made.append(("Chat Conversation", conv.name))

		msg = frappe.new_doc("Chat Message")
		msg.conversation = conv.name
		msg.message_type = "User"
		msg.content = "secret"
		msg.insert()
		self.msg = msg.name
		self._made.append(("Chat Message", msg.name))
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		for doctype, name in reversed(self._made):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
		frappe.db.commit()


class TestAnOutsiderSeesNothing(ChatPrivacyCase):
	"""AC1: B must not get A's conversation from the list, and a direct read fails."""

	def test_the_list_does_not_return_someone_elses_conversation(self):
		frappe.set_user(OUTSIDER)
		names = frappe.get_list("Chat Conversation", pluck="name", limit_page_length=0)

		self.assertNotIn(self.conv, names)

	def test_the_list_does_not_return_someone_elses_messages(self):
		frappe.set_user(OUTSIDER)
		names = frappe.get_list("Chat Message", pluck="name", limit_page_length=0)

		self.assertNotIn(self.msg, names)

	def test_reading_the_conversation_directly_is_refused(self):
		frappe.set_user(OUTSIDER)

		self.assertFalse(frappe.has_permission("Chat Conversation", "read", doc=self.conv))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Chat Conversation", self.conv).check_permission("read")

	def test_reading_the_message_directly_is_refused(self):
		frappe.set_user(OUTSIDER)

		self.assertFalse(frappe.has_permission("Chat Message", "read", doc=self.msg))

	def test_an_outsider_cannot_edit_or_delete_the_message(self):
		frappe.set_user(OUTSIDER)

		self.assertFalse(frappe.has_permission("Chat Message", "write", doc=self.msg))
		self.assertFalse(frappe.has_permission("Chat Message", "delete", doc=self.msg))

	def test_an_outsider_cannot_post_into_the_conversation(self):
		frappe.set_user(OUTSIDER)
		msg = frappe.new_doc("Chat Message")
		msg.conversation = self.conv
		msg.message_type = "User"
		msg.content = "intruding"

		self.assertFalse(chat_message_has_permission(msg, "create", OUTSIDER))


class TestThePersonWhoHadItKeepsAccess(ChatPrivacyCase):
	def test_the_owner_still_sees_their_own(self):
		frappe.set_user(OWNER)

		self.assertIn(self.conv, frappe.get_list("Chat Conversation", pluck="name", limit_page_length=0))
		self.assertIn(self.msg, frappe.get_list("Chat Message", pluck="name", limit_page_length=0))
		self.assertTrue(frappe.has_permission("Chat Conversation", "read", doc=self.conv))
		self.assertTrue(frappe.has_permission("Chat Message", "write", doc=self.msg))

	def test_a_listed_participant_who_did_not_start_it_is_refused(self):
		"""A conversation is the creator's alone. Nothing ever lists anyone else as
		a participant in practice, so the row on the fixture is the only one that
		would have had a claim — and if_owner refuses it."""
		frappe.set_user(GUEST_OF)

		self.assertTrue(is_participant(self.conv, GUEST_OF))
		self.assertNotIn(self.conv, frappe.get_list("Chat Conversation", pluck="name", limit_page_length=0))
		self.assertFalse(frappe.has_permission("Chat Conversation", "read", doc=self.conv))
		self.assertFalse(frappe.has_permission("Chat Conversation", "write", doc=self.conv))

	def test_nobody_but_an_administrator_may_delete_a_conversation(self):
		frappe.set_user(OWNER)

		self.assertFalse(frappe.has_permission("Chat Conversation", "delete", doc=self.conv))


class TestTheAgentReplyStillLands(ChatPrivacyCase):
	"""AC2: the map's Save Response task runs in the asker's own session."""

	def test_a_bot_reply_inserts_and_the_owner_can_read_it(self):
		frappe.set_user(OWNER)
		reply = frappe.new_doc("Chat Message")
		reply.conversation = self.conv
		reply.message_type = "Bot"
		reply.content = "here is your answer"
		reply.insert()
		self._made.append(("Chat Message", reply.name))

		self.assertTrue(frappe.has_permission("Chat Message", "read", doc=reply.name))

		frappe.set_user(OUTSIDER)
		self.assertFalse(frappe.has_permission("Chat Message", "read", doc=reply.name))

	def test_the_memory_thread_store_still_writes(self):
		"""It inserts with permissions ignored, and must keep doing so."""
		frappe.set_user(OWNER)
		conv = frappe.new_doc("Chat Conversation")
		conv.agent_mode = "one_bpmn:agent-memory"
		conv.title = "one_bpmn:inst:node"
		conv.insert(ignore_permissions=True)
		self._made.append(("Chat Conversation", conv.name))

		self.assertEqual(conv.owner, OWNER)


class TestSystemManagerSeesEverything(ChatPrivacyCase):
	"""AC3: the Sessions screen lists every conversation as before."""

	def test_a_system_manager_sees_another_persons_conversation(self):
		manager = _user("wi2364_manager@example.com", roles=("System Manager",))
		frappe.set_user(manager)

		self.assertIn(self.conv, frappe.get_list("Chat Conversation", pluck="name", limit_page_length=0))
		self.assertTrue(frappe.has_permission("Chat Conversation", "read", doc=self.conv))
		self.assertTrue(frappe.has_permission("Chat Message", "read", doc=self.msg))

	def test_the_sessions_screen_still_lists_it(self):
		from one_bpmn.api.sessions_api import list_conversations

		manager = _user("wi2364_manager@example.com", roles=("System Manager",))
		frappe.set_user(manager)
		out = list_conversations()
		rows = out.get("conversations") if isinstance(out, dict) else out

		self.assertIn(self.conv, [r.get("name") for r in rows])

	def test_the_sessions_screen_refuses_someone_who_is_not_an_administrator(self):
		from one_bpmn.api.sessions_api import list_conversations

		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			list_conversations()


class TestAdministratorOwnedRowsGoBackToTheirPerson(ChatPrivacyCase):
	"""The frontend used to save conversations as Administrator. Under if_owner
	that hides them from the person who had them, so the patch hands them back
	wherever the person is still on the record."""

	def _saved_as_administrator(self, participant=None, first_sender=None):
		frappe.set_user("Administrator")
		conv = frappe.new_doc("Chat Conversation")
		conv.agent_mode = "ProsAlly"
		conv.title = "saved by the frontend as Administrator"
		if participant:
			conv.append("participants", {"user": participant})
		conv.insert(ignore_permissions=True)
		self._made.append(("Chat Conversation", conv.name))
		if first_sender:
			msg = frappe.new_doc("Chat Message")
			msg.conversation = conv.name
			msg.message_type = "User"
			msg.sender = first_sender
			msg.content = "mine"
			msg.insert(ignore_permissions=True)
			self._made.append(("Chat Message", msg.name))
		return conv.name

	def _run_patch(self):
		from one_bpmn.one_bpmn.patches.v1_0 import chat_conversation_owner_is_the_person as patch

		patch.execute()

	def test_the_participant_row_names_the_owner(self):
		conv = self._saved_as_administrator(participant=OWNER)
		self._run_patch()
		self.assertEqual(frappe.db.get_value("Chat Conversation", conv, "owner"), OWNER)
		frappe.set_user(OWNER)
		self.assertTrue(frappe.has_permission("Chat Conversation", "read", doc=conv))

	def test_the_first_message_names_the_owner_when_there_is_no_participant(self):
		conv = self._saved_as_administrator(first_sender=OWNER)
		self._run_patch()
		self.assertEqual(frappe.db.get_value("Chat Conversation", conv, "owner"), OWNER)

	def test_a_row_with_no_trace_of_a_person_stays_administrators(self):
		conv = self._saved_as_administrator()
		self._run_patch()
		self.assertEqual(frappe.db.get_value("Chat Conversation", conv, "owner"), "Administrator")

	def test_a_user_message_owned_by_administrator_is_aligned_to_its_sender(self):
		conv = self._saved_as_administrator(participant=OWNER, first_sender=OWNER)
		msg = frappe.db.get_value("Chat Message", {"conversation": conv, "message_type": "User"}, "name")
		self.assertEqual(frappe.db.get_value("Chat Message", msg, "owner"), "Administrator")
		self._run_patch()
		self.assertEqual(frappe.db.get_value("Chat Message", msg, "owner"), OWNER)


class TestAnA2AClientIsOwnerScopedToo(ChatPrivacyCase):
	"""An inbound A2A turn creates its own conversation — run_chat_turn calls
	invoke_agent with no conversation — so the badge role never needs to reach
	one it did not start, and carries if_owner like every other role."""

	A2A_USER = "wi2364_a2a@example.com"

	def setUp(self):
		super().setUp()
		from one_bpmn.agents.a2a.principal import A2A_CLIENT_ROLE, ensure_client_role

		ensure_client_role()
		_user(self.A2A_USER, roles=(A2A_CLIENT_ROLE,))
		frappe.clear_cache(user=self.A2A_USER)

	def test_a_client_cannot_read_someone_elses_conversation(self):
		frappe.set_user(self.A2A_USER)

		self.assertNotIn(self.conv, frappe.get_list("Chat Conversation", pluck="name", limit_page_length=0))
		self.assertFalse(frappe.has_permission("Chat Conversation", "read", doc=self.conv))
		self.assertFalse(frappe.has_permission("Chat Message", "read", doc=self.msg))

	def test_a_client_still_owns_the_conversation_it_starts(self):
		frappe.set_user(self.A2A_USER)
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		conv = create_agent_conversation("lumina_general_chat", title="inbound turn")
		self._made.append(("Chat Conversation", conv))

		self.assertEqual(frappe.db.get_value("Chat Conversation", conv, "owner"), self.A2A_USER)
		self.assertTrue(frappe.has_permission("Chat Conversation", "read", doc=conv))
		self.assertTrue(frappe.has_permission("Chat Conversation", "write", doc=conv))
