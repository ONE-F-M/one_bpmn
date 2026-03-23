
import logging
from SpiffWorkflow import TaskState

logger = logging.getLogger('spiff_engine')

class Instance:
	"""
	A wrapper around SpiffWorkflow BpmnWorkflow to provide a cleaner interface
	and handle persistence hooks.
	"""
	def __init__(self, wf_id, workflow, save=None):
		self.wf_id = wf_id
		self.workflow = workflow
		self._save = save

	def save(self):
		if self._save:
			self._save(self)

	def get_data(self):
		return self.workflow.last_task.data if self.workflow.last_task else {}

	def run_all(self):
		"""
		Runs the workflow until it reaches a point where it can no longer proceed.
		"""
		self.workflow.do_engine_steps()
		self.save()

	def get_ready_tasks(self):
		"""
		Returns a list of tasks that are ready for user interaction.
		"""
		return self.workflow.get_tasks(TaskState.READY)

	def complete_task(self, task):
		"""
		Completes a task and continues workflow execution.
		"""
		self.workflow.complete_task_from_id(task.id)
		self.run_all()
