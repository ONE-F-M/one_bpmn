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
        self.assertEqual(history[0], {"role": "user", "content": "Hello assistant"})
        self.assertEqual(history[1], {"role": "assistant", "content": "Hello human"})
        
        # 4. State management
        state = get_or_create_state(conv_name, initial_data={"step": "start"})
        self.assertEqual(state, {"step": "start"})
        
        update_state(conv_name, {"step": "step2"})
        state2 = get_or_create_state(conv_name)
        self.assertEqual(state2, {"step": "step2"})
        
        # 5. Verify no database records were inserted in tabChat Conversation or tabChat Message
        self.assertFalse(frappe.db.exists("Chat Conversation", conv_name))
