# Copyright (c) 2025, One BPMN and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ProcessaSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_callback_secret: DF.Password | None
		agent_sandbox_caller_key: DF.Password | None
		agent_sandbox_url: DF.Data | None
		ai_health_alert_recipients: DF.Data | None
		archive_action: DF.Literal["Archive", "Delete"]
		ba_api_key: DF.Password | None
		ba_api_secret: DF.Password | None
		ba_site_url: DF.Data | None
		connect_to_production: DF.Check
		connector_handler_app: DF.Data | None
		conversation_ttl_days: DF.Int
		copilot_enterprise_slug: DF.Data | None
		copilot_metrics_pat: DF.Password | None
		copilot_org_name: DF.Data | None
		customization_app: DF.Data | None
		default_compaction_model: DF.Link | None
		default_context_token_budget: DF.Int
		default_llm_provider: DF.Literal["gemini", "anthropic", "openai"]
		default_memory_distill_model: DF.Link | None
		default_memory_reconcile_model: DF.Link | None
		dev_agent_report_recipients: DF.Data | None
		dev_agent_weekly_report_enabled: DF.Check
		enable_ba_sync: DF.Check
		enable_mcp_tools_for_user_planning_agent: DF.Check
		enable_observability: DF.Check
		enable_staging_sync: DF.Check
		enabled: DF.Check
		eval_alert_recipients: DF.Data | None
		eval_concurrency: DF.Int
		github_token: DF.Password | None
		google_chat_service_account_json: DF.Password | None
		google_directory_account: DF.Data | None
		google_translate_api_key: DF.Password | None
		instance_type: DF.Literal["Local", "Production", "Staging", "BA"]
		langfuse_base_url: DF.Data | None
		langfuse_public_key: DF.Password | None
		langfuse_secret_key: DF.Password | None
		langsmith_api_key: DF.Password | None
		langsmith_project_name: DF.Data | None
		lock_release_roles: DF.SmallText | None
		mcp_tools_enabled: DF.Check
		memory_embedding_model: DF.Literal["sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5", "snowflake/snowflake-arctic-embed-xs", "snowflake/snowflake-arctic-embed-s", "BAAI/bge-small-en", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "Disabled"]
		memory_importance_weight: DF.Float
		memory_prune_low_importance_days: DF.Int
		memory_prune_min_confidence: DF.Float
		memory_prune_uncorroborated_days: DF.Int
		memory_recency_weight: DF.Float
		memory_retrieval_budget_ms: DF.Int
		memory_scope_row_alert: DF.Int
		memory_semantic_weight: DF.Float
		memory_total_row_alert: DF.Int
		memory_trust_hierarchy: DF.SmallText | None
		nightly_eval_grading_model: DF.Link | None
		nightly_eval_spend_cap: DF.Currency
		observability_retry_attempts: DF.Int
		observability_sanitization_level: DF.Literal["None", "Partial", "Full"]
		openai_search_context: DF.Literal["low", "medium", "high"]
		production_api_key: DF.Password | None
		production_api_secret: DF.Password | None
		production_notification_account: DF.Link | None
		production_url: DF.Data | None
		push_service_account_json: DF.Password | None
		push_token_doctype: DF.Link | None
		push_token_field: DF.Data | None
		push_token_user_field: DF.Data | None
		sandbox_job_max_parallel: DF.Int
		sandbox_job_name: DF.Data | None
		sandbox_job_processa_url: DF.Data | None
		sandbox_job_project: DF.Data | None
		sandbox_job_region: DF.Data | None
		script_binop_multiply_threshold: DF.Int
		script_block_all_imports: DF.Check
		script_block_functiondef: DF.Check
		script_block_lambda: DF.Check
		script_block_while: DF.Check
		script_strict_builtins: DF.Check
		script_strict_frappe_attrs: DF.Check
		staging_api_key: DF.Password | None
		staging_api_secret: DF.Password | None
		staging_site_url: DF.Data | None
		token_estimator_chars_per_token: DF.Int
		user_story_template: DF.SmallText | None
	# end: auto-generated types
	def validate(self):
		self._validate_embedding_model()
		self._validate_push_token_source()

	def _validate_push_token_source(self):
		"""Refuse token source fields that the Token DocType does not have."""
		if not self.push_token_doctype:
			return
		meta = frappe.get_meta(self.push_token_doctype)
		for fieldname in (self.push_token_user_field, self.push_token_field):
			if not meta.has_field(fieldname):
				frappe.throw(
					_("{0} has no field {1}.").format(self.push_token_doctype, frappe.bold(fieldname)),
					title=_("Push Token Source"),
				)

	def _validate_embedding_model(self):
		"""Refuse an embedding model that cannot produce the width of the stored
		column.

		The Select only offers models that produce the right width, so this is
		the second line: a patch, a fixture or an API write can set the field
		without ever passing through the form. A model of the wrong width is not
		rejected at save time by the database either, because nothing is written
		then; every LATER memory write fails inside a try/except, logs one line
		and carries on, so semantic search stops working with nothing on screen
		to say so. That is the failure this exists to make impossible.

		Only runs when the value actually changed, so an administrator editing
		an unrelated setting is never made to wait for a model to load, and a
		machine that has lost its model cache can still be configured. The
		comparison is against what is stored, not Frappe's before-save copy,
		because a patch or a fixture can reach ``validate`` without one.

		Skipped during install and migrate, where a save of this Single would
		otherwise pull a model download into the middle of a deployment.
		"""
		from one_bpmn.ai_agent_memory.doctype.ai_memory.ai_memory import EMBEDDING_DIMENSIONS
		from one_bpmn.ai_agent_memory.embedding import SEMANTIC_DISABLED

		model = (self.memory_embedding_model or "").strip()
		if not model or model == SEMANTIC_DISABLED:
			return
		if frappe.flags.in_install or frappe.flags.in_migrate:
			return

		stored = (frappe.db.get_single_value("Processa Settings", "memory_embedding_model") or "").strip()
		if model == stored:
			return

		try:
			from one_bpmn.ai_agent_memory.embedding import probe_model

			dimensions = probe_model(model)
		except Exception as e:
			frappe.throw(
				_("{0} could not be loaded, so semantic memory search would silently stop working: {1}").format(
					frappe.bold(model), e
				),
				title=_("Embedding Model Unusable"),
			)

		if dimensions != EMBEDDING_DIMENSIONS:
			frappe.throw(
				_(
					"{0} produces {1} numbers per memory, but the stored column holds {2}. "
					"Every memory written with it would fail to store, leaving semantic search off. "
					"Choose a model that produces {2}, or choose Disabled."
				).format(frappe.bold(model), dimensions, EMBEDDING_DIMENSIONS),
				title=_("Embedding Model Does Not Fit"),
			)
