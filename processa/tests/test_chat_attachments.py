# Copyright (c) 2026, one-fm and contributors
"""Files attached to a chat turn reach the model: images as images, text files as text, the rest named as not read."""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.agent_runtime.direct_api import DirectApiExecutor
from processa.processa_engine.agent_runtime.executor import ExecutorConfig, ExecutorContext
from processa.processa_engine.agent_runtime.llm_anthropic import AnthropicAdapter
from processa.processa_engine.agent_runtime.llm_gemini import GeminiAdapter
from processa.processa_engine.agent_runtime.llm_openai import OpenAIAdapter
from processa.processa_engine.dispatch import attachments
from processa.tests.test_adapter_tool_controls import _OpenAICompletions
from processa.tests.test_anthropic_sampling_params import _model
from processa.tests.test_temperature_reaches_the_provider import _Stream

PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
IMAGE = {"media_type": "image/png", "data": base64.b64encode(PNG).decode()}
TURN = [{"role": "user", "content": "what is in this picture?", "images": [IMAGE]}]


def _file(name, content):
	return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 0}).insert(
		ignore_permissions=True
	)


class TestReadAttachments(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_images_text_and_unreadable_files_are_each_handled(self):
		image = _file("screen.png", PNG)
		note = _file("steps.txt", b"Click Generate Invoice, then wait.")
		clip = _file("clip.mp4", b"\x00\x00\x00\x18ftypmp42")
		images, text = attachments.read_attachments(
			[image.file_url, note.file_url, clip.file_url, "/files/gone.png"]
		)
		self.assertEqual(images, [IMAGE])
		self.assertIn("Click Generate Invoice, then wait.", text)
		self.assertIn("clip.mp4 was not read", text)
		self.assertIn("gone.png was not read", text)

	def test_an_image_over_the_limit_is_not_read(self):
		image = _file("big.png", PNG)
		with patch.object(attachments, "MAX_IMAGE_BYTES", 10):
			images, text = attachments.read_attachments([image.file_url])
		self.assertEqual(images, [])
		self.assertIn("big.png was not read", text)

	def test_no_files_gives_nothing(self):
		self.assertEqual(attachments.read_attachments([]), ([], ""))
		self.assertEqual(attachments.read_attachments(None), ([], ""))


class TestAdaptersSendImages(FrappeTestCase):
	def test_anthropic_sends_an_image_block_after_the_text(self):
		adapter = AnthropicAdapter(api_key="test-key-not-real", model="claude-sonnet-4-5")
		sent = []
		adapter._client = SimpleNamespace(messages=SimpleNamespace(stream=_Stream(sent)))
		asyncio.run(adapter.step("sys", TURN))
		content = sent[0]["messages"][-1]["content"]
		self.assertEqual(content[-1], {"type": "image", "source": {"type": "base64", **IMAGE}})
		self.assertIn("what is in this picture?", "".join(b.get("text", "") for b in content))

	def test_openai_sends_the_image_as_a_data_url(self):
		adapter = OpenAIAdapter(api_key="test-key-not-real", model="gpt-4o-mini")
		sent = []
		message = SimpleNamespace(content="ok", tool_calls=None)
		adapter._client = SimpleNamespace(
			chat=SimpleNamespace(completions=_OpenAICompletions(sent, message, "stop"))
		)
		asyncio.run(adapter.step("s", TURN))
		content = sent[0]["messages"][-1]["content"]
		self.assertEqual(content[1]["image_url"]["url"], f"data:image/png;base64,{IMAGE['data']}")

	def test_gemini_sends_the_image_bytes(self):
		adapter = GeminiAdapter(api_key="test-key-not-real", model="gemini-2.5-flash")
		sent = []

		async def generate_content(model, contents, config):
			sent.append(contents)
			part = SimpleNamespace(function_call=None, text="ok")
			return SimpleNamespace(
				candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], usage_metadata=None
			)

		adapter._client = SimpleNamespace(
			aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
		)
		asyncio.run(adapter.step("s", TURN))
		self.assertEqual(sent[0][-1].parts[1].inline_data.data, PNG)


class TestImagesTakeTheAdapterPath(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_call_with_an_image_and_no_tools_goes_through_the_adapter(self):
		config = ExecutorConfig(
			provider_name="Anthropic",
			model=_model("zz-attachments-model", 1),
			user_prompt="look",
			images=[IMAGE],
		)
		with patch.object(DirectApiExecutor, "_run_with_tools", return_value="adapter path") as adapter_path:
			self.assertEqual(DirectApiExecutor().run(config, ExecutorContext()), "adapter path")
		self.assertEqual(adapter_path.call_args.args[0].images, [IMAGE])
