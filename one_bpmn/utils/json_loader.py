import frappe
import json
import os


def get_json_file(file_name: str, folder: str):
	"""
	Load and return JSON data from a file in the specified folder.

	Args:
		file_name (str): The name of the JSON file (must end with `.json`).
		folder (str): The absolute path to the folder containing the JSON file.

	Returns:
		dict: Parsed JSON data from the file.
	"""
	data = {}
	if not file_name.endswith(".json"):
		frappe.log_error("Only JSON files are allowed. Please ensure the file ends with '.json'.")

	file_path = os.path.join(folder, file_name)

	if not os.path.isfile(file_path):
		frappe.log_error(f"File not found: {file_path}")

	try:
		with open(file_path, "r") as f:
			data = json.load(f)

	except json.JSONDecodeError as e:
		frappe.log_error(title=f"Invalid JSON format in file {file_path}", message=str(e))

	except Exception as e:
		frappe.log_error(title=f"An error occurred while reading the file {file_path}", message=str(e))

	return data
