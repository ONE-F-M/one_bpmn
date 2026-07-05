import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { AI_SPARKLE_DATA_URI } from "../shared/aiSparkleIcon";

/**
 * Adds an "AI Task Selector" entry to the bpmn-js "Change element"
 * (bpmn-replace) popup menu for Ad-hoc Subprocesses (WI-001351).
 *
 * Selecting it tags the subprocess ITSELF with
 * spiffworkflow:serviceType="ai_task_selector" and defaults
 * spiffworkflow:aiToolSources to "both" (diagram inner tasks + AI Agent
 * Tool registry, the merged-pool design). Selecting it again on an
 * already-tagged subprocess removes the selector configuration.
 *
 * The ai* attributes are declared on the AdhocAiTaskSelectorExtension
 * moddle extension (see BpmnEditor.vue) so they round-trip through
 * save/reload. Compile-time validation (provider required, raw-key lint)
 * lives in api/compilation.py.
 */

// Run after the built-in ReplaceMenuProvider (priority 1000) so the standard
// subprocess options are already present and we simply append ours.
const LOW_PRIORITY = 500;

const ENTRY_ID = "replace-with-ai-task-selector";

const SELECTOR_ATTRS = [
  "spiffworkflow:serviceType",
  "spiffworkflow:aiProvider",
  "spiffworkflow:aiModel",
  "spiffworkflow:aiSystemPrompt",
  "spiffworkflow:aiUserPrompt",
  "spiffworkflow:aiToolSources",
];

export default function AiTaskSelectorMenuProvider(popupMenu, modeling, translate, selection) {

  this._popupMenu = popupMenu;
  this._modeling = modeling;
  this._translate = translate;
  this._selection = selection;

  popupMenu.registerProvider("bpmn-replace", LOW_PRIORITY, this);
}

AiTaskSelectorMenuProvider.$inject = [
  "popupMenu",
  "modeling",
  "translate",
  "selection",
];

AiTaskSelectorMenuProvider.prototype.getPopupMenuEntries = function(target) {
  const self = this;

  return function(entries) {
    if (Array.isArray(target) || !is(target, "bpmn:AdHocSubProcess")) {
      return entries;
    }

    const bo = getBusinessObject(target);
    const isSelector = (bo.get("spiffworkflow:serviceType") ?? "") === "ai_task_selector";

    entries[ENTRY_ID] = {
      label: self._translate(isSelector ? "Remove AI Task Selector" : "AI Task Selector"),
      imageUrl: AI_SPARKLE_DATA_URI,

      action: function() {
        if (isSelector) {
          const cleared = {};
          for (const attr of SELECTOR_ATTRS) {
            cleared[attr] = undefined;
          }
          self._modeling.updateModdleProperties(target, bo, cleared);
        } else {
          self._modeling.updateModdleProperties(target, bo, {
            "spiffworkflow:serviceType": "ai_task_selector",
            "spiffworkflow:aiToolSources": "both",
          });
        }

        // Re-select so the properties panel re-renders against the new state.
        if (self._selection) {
          self._selection.select(null);
          self._selection.select(target);
        }

        return target;
      },
    };

    return entries;
  };
};
