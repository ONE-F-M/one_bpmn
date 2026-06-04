# one_bpmn/api/__init__.py
# This package contains the one_bpmn API, organized into submodules:
#
#   process_map_api    — CRUD for BPMN Process Model and Process records
#   compilation        — compile/deploy/disable process models
#   workflow_state     — apply workflow states and docstatus transitions
#   editability        — Pathfinder Log cross-site editability checks
#   instance_api       — process instance lifecycle (start, complete, list)
#   server_script_api  — server script CRUD, Logix/ProSally integration
#   canvas_comments    — canvas comment and element asset management
#   notification_api   — in-app notification creation
#   shape_library      — custom shape library CRUD
#   script_version_history — server script version history and restore
#   version_history    — diagram XML version history
#   utils              — shared helpers (role checks, field lookups)
