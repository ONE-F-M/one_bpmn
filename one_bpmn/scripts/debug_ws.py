import frappe, json

instances = frappe.get_all('BPMN Process Instance', filters={'status': 'Active'}, fields=['name', 'workflow_state'], limit=1)
if instances:
    ws = json.loads(instances[0].workflow_state or '{}')
    tasks = ws.get('tasks', {})
    for uuid, t in list(tasks.items())[:15]:
        print(f'UUID: {uuid[:12]}...  task_spec: {t.get("task_spec", "?")}  state: {t.get("state", "?")}')
    print(f'---Total tasks: {len(tasks)}')
    print(f'---Top-level keys: {list(ws.keys())}')
else:
    print('No active instances found')
