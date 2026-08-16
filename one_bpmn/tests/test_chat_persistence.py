import frappe
from frappe.tests.utils import FrappeTestCase
from one_bpmn.utils.chat_persistence import (
    create_conversation,
    close_conversation,
    save_user_message,
    save_bot_message,
    load_history,
    get_or_create_state,
    update_state
)

class TestChatPersistence(FrappeTestCase):
    def test_cache_chat_lifecycle(self):
        # 1. Create conversation
        conv_name = create_conversation(
            agent_mode="ProsAlly",
            title="Test Chat",
            user="Administrator"
        )
        self.assertTrue(conv_name.startswith("CONV-"))
        
        # 2. Save user and bot messages
        msg1 = save_user_message(conv_name, "Hello assistant")
        msg2 = save_bot_message(conv_name, "Hello human", metadata={"intent": "GREET"})
        
        self.assertTrue(msg1.startswith("MSG-"))
        self.assertTrue(msg2.startswith("MSG-"))
        
        # 3. Load history
        history = load_history(conv_name, limit=5)
        self.assertEqual(len(history), 2)
        # Compared field by field rather than as whole dicts: load_history now
        # returns the Chat Message name (WI-001822) and its creation timestamp
        # (WI-002047) alongside role and content. A strict equality would fail on
        # those and invite someone to "fix" it by deleting them.
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Hello assistant")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["content"], "Hello human")
        # WI-001822: the row id, so a redrawn reply can still be rated
        self.assertEqual(history[0]["message"], msg1)
        self.assertEqual(history[1]["message"], msg2)
        # WI-002047: every history row carries the message's creation timestamp
        for row in history:
            self.assertTrue(row["timestamp"])
        
        # 4. State management
        state = get_or_create_state(conv_name, initial_data={"step": "start"})
        self.assertEqual(state, {"step": "start"})
        
        update_state(conv_name, {"step": "step2"})
        state2 = get_or_create_state(conv_name)
        self.assertEqual(state2, {"step": "step2"})
        
        # 5. Verify no database records were inserted in tabChat Conversation or tabChat Message
        self.assertFalse(frappe.db.exists("Chat Conversation", conv_name))
