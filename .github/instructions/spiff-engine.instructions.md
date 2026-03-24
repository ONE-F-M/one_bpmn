---
applyTo: "spiff/src/bpmn/**,spiff/src/moddle/**,spiff/src/renderers/**,spiff/src/rules/**"
---

# BPMN Engine Integration Review

These files extend bpmn-js and Spiffworkflow moddle definitions.

- Changes to moddle extensions MUST maintain backward compatibility with existing BPMN XML.
- Custom renderers must handle missing/null element properties gracefully.
- Custom rules must not silently block valid BPMN operations.
- Keep bpmn-js extension points minimal. Prefer configuring existing features over custom implementations.
- Flag any new bpmn-js module that duplicates functionality of an existing bpmn-js extension.
