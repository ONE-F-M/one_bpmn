import { SelectEntry, TextFieldEntry, isSelectEntryEdited, isTextFieldEntryEdited } from '@bpmn-io/properties-panel';
import { useService } from 'bpmn-js-properties-panel';
import { getBusinessObject } from 'bpmn-js/lib/util/ModelUtil';
import { h } from 'preact';

export function TimerProps(props) {
  const { element } = props;

  const entries = [];

  const getEventDefinition = () => {
    const bo = getBusinessObject(element);
    return (bo.eventDefinitions || []).find(e => e.$type === 'bpmn:TimerEventDefinition');
  };

  const timerDef = getEventDefinition();
  if (!timerDef) {
    return entries;
  }

  entries.push({
    id: 'spiffworkflow-schedulerFrequency',
    element,
    component: SchedulerFrequencyComponent,
    isEdited: isSelectEntryEdited
  });

  const currentFrequency = timerDef.get('spiffworkflow:schedulerFrequency');

  if (currentFrequency === 'Cron') {
    entries.push({
      id: 'spiffworkflow-cronExpression',
      element,
      component: CronExpressionComponent,
      isEdited: isTextFieldEntryEdited
    });
  }

  return entries;
}

function SchedulerFrequencyComponent(props) {
  const { element, id } = props;
  const modeling = useService('modeling');
  const translate = useService('translate');

  const getEventDefinition = () => {
    const bo = getBusinessObject(element);
    return (bo.eventDefinitions || []).find(e => e.$type === 'bpmn:TimerEventDefinition');
  };

  const timerDef = getEventDefinition();

  const getValue = () => {
    return timerDef ? (timerDef.get('spiffworkflow:schedulerFrequency') || '') : '';
  };

  const setValue = (value) => {
    if (!timerDef) return;
    const updates = { 'spiffworkflow:schedulerFrequency': value || undefined };
    if (value !== 'Cron') {
      updates['spiffworkflow:cronExpression'] = undefined;
    }
    // Update the moddle object inside the element
    modeling.updateModdleProperties(element, timerDef, updates);
  };

  const getOptions = () => {
    return [
      { label: translate('None'), value: '' },
      { label: translate('All'), value: 'All' },
      { label: translate('Hourly'), value: 'Hourly' },
      { label: translate('Daily'), value: 'Daily' },
      { label: translate('Weekly'), value: 'Weekly' },
      { label: translate('Monthly'), value: 'Monthly' },
      { label: translate('Yearly'), value: 'Yearly' },
      { label: translate('Cron'), value: 'Cron' },
    ];
  };

  return h(SelectEntry, {
    element,
    id,
    label: translate('Scheduler Frequency'),
    getValue,
    setValue,
    getOptions
  });
}

function CronExpressionComponent(props) {
  const { element, id } = props;
  const modeling = useService('modeling');
  const translate = useService('translate');
  const debounce = useService('debounceInput');

  const getEventDefinition = () => {
    const bo = getBusinessObject(element);
    return (bo.eventDefinitions || []).find(e => e.$type === 'bpmn:TimerEventDefinition');
  };

  const timerDef = getEventDefinition();

  const getValue = () => {
    return timerDef ? (timerDef.get('spiffworkflow:cronExpression') || '') : '';
  };

  const setValue = (value) => {
    if (!timerDef) return;
    modeling.updateModdleProperties(element, timerDef, {
      'spiffworkflow:cronExpression': value || undefined
    });
  };

  return h(TextFieldEntry, {
    element,
    id,
    label: translate('Cron Expression'),
    description: translate('e.g., 0 0 * * *'),
    getValue,
    setValue,
    debounce
  });
}
