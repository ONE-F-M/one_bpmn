import frappe


def execute():
	"""Queue the embedding backfill for AI Memory rows written before semantic
	retrieval existed. Runs in the background so migrate does not wait on the
	embedding model; on a database without the VECTOR column the job exits at
	once and the next migrate after the upgrade queues it again."""
	from one_bpmn.agents.memory.embedding_backfill import enqueue_backfill

	if frappe.flags.in_test:
		return
	enqueue_backfill()
