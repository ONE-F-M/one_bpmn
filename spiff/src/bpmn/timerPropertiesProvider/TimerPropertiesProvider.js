import { TimerProps } from './TimerProps';
import { is } from 'bpmn-js/lib/util/ModelUtil';

const LOW_PRIORITY = 500;

export default class TimerPropertiesProvider {
  constructor(propertiesPanel, translate) {
    propertiesPanel.registerProvider(LOW_PRIORITY, this);
    this.translate = translate;
  }

  getGroups(element) {
    return (groups) => {
      // It can be a StartEvent or CatchEvent
      if (is(element, 'bpmn:Event')) {
        const businessObject = element.businessObject;
        const eventDefinitions = businessObject.eventDefinitions || [];
        const timerEventDefinition = eventDefinitions.find(e => e.$type === 'bpmn:TimerEventDefinition');

        if (timerEventDefinition) {
          groups.push({
            id: 'spiffworkflow-timer-configuration',
            label: this.translate('Timer Configuration'),
            entries: TimerProps({ element })
          });
        }
      }
      return groups;
    };
  }
}

TimerPropertiesProvider.$inject = ['propertiesPanel', 'translate'];
