# Copyright (c) 2026, one-fm and contributors
# Nothing is imported here on purpose.
#
# Handlers used to register themselves via an @connector decorator, which meant
# importing this package had a side effect the dispatcher depended on. They are
# now named on their BPMN Connector Operation row and resolved with
# frappe.get_attr, which imports the module on demand — so there is no registry
# to populate and no import order to get right.
