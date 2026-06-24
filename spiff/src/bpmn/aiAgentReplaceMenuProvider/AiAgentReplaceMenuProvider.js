import { is, getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { AI_SPARKLE_DATA_URI } from "../shared/aiSparkleIcon";


/**
 * Adds an "AI Agent Task" entry to the bpmn-js "Change element" (bpmn-replace)
 * popup menu.
 *
 * Selecting it morphs the element into a bpmn:ServiceTask tagged with
 * spiffworkflow:serviceType="ai_agent" — the same tag the Service Type
 * dropdown in the properties panel sets. The ai* configuration attributes are
 * already declared on the ServiceTaskApplyWorkflowExtension moddle extension
 * (see BpmnEditor.vue), so they round-trip through save/reload.
 *
 * Registered with a priority below the stock ReplaceMenuProvider (default
 * 1000) so this runs afterwards and appends to the standard task entries.
 */

// Run after the built-in ReplaceMenuProvider (priority 1000) so the standard
// task options are already present and we simply append ours.
const LOW_PRIORITY = 500;

const AI_AGENT_ENTRY_ID = "replace-with-ai-agent-task";

export default function AiAgentReplaceMenuProvider(popupMenu, bpmnReplace, modeling, translate, selection) {

  this._popupMenu = popupMenu;
  this._bpmnReplace = bpmnReplace;
  this._modeling = modeling;
  this._translate = translate;
  this._selection = selection;


  popupMenu.registerProvider("bpmn-replace", LOW_PRIORITY, this);
}

AiAgentReplaceMenuProvider.$inject = [
  "popupMenu",
  "bpmnReplace",
  "modeling",
  "translate",
  "selection",

];

AiAgentReplaceMenuProvider.prototype.getPopupMenuEntries = function(target) {
  const self = this;

  // Use the middleware (function) form so we extend, rather than replace, the
  // entries contributed by the stock ReplaceMenuProvider.
  return function(entries) {
    // Arrays of selected elements and non-task shapes are out of scope.
    if (Array.isArray(target) || !is(target, "bpmn:Task")) {
      return entries;
    }

    entries[AI_AGENT_ENTRY_ID] = {
      label: self._translate("AI Agent Task"),
      imageUrl: AI_SPARKLE_DATA_URI,

      action: function() {
        let element = target;

        // Only morph when it is not already a Service Task — avoids an
        // unnecessary element replacement when toggling the subtype.
        if (!is(target, "bpmn:ServiceTask")) {
          element = self._bpmnReplace.replaceElement(target, {
            type: "bpmn:ServiceTask",
          });
        }

        self._modeling.updateModdleProperties(
          element,
          getBusinessObject(element),
          { "spiffworkflow:serviceType": "ai_agent" }
        );

        // Re-select the element so the properties panel re-renders against the
        // final state and shows the AI Agent group immediately (without this,
        // morphing TO an AI Agent Task leaves the panel stale until the user
        // clicks away and back).
        if (self._selection) {
          self._selection.select(null);
          self._selection.select(element);
        }


        return element;
      },
    };

    return entries;
  };
};
