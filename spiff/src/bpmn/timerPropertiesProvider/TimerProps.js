import { SelectEntry, TextFieldEntry, isSelectEntryEdited, isTextFieldEntryEdited } from '@bpmn-io/properties-panel';
import { useService } from 'bpmn-js-properties-panel';
import { getBusinessObject } from 'bpmn-js/lib/util/ModelUtil';
import { h } from 'preact';

const FREQUENCY_EXPLANATIONS = {
  All: {
    title: 'All (Every 60 seconds)',
    description: 'Triggers every 60 seconds (1 minute) as long as the scheduler is running.',
    example: 'If the scheduler starts at 10:00:00, the next runs will be at 10:01:00, 10:02:00, 10:03:00, and so on.',
    note: 'Use with caution — this is the most frequent option and may cause high load.'
  },
  Hourly: {
    title: 'Hourly',
    description: 'Triggers once every hour, at the start of the hour (minute 0).',
    example: 'Runs at 01:00, 02:00, 03:00, … , 23:00, 00:00 every day.',
    note: 'Equivalent to the cron expression: 0 * * * *'
  },
  Daily: {
    title: 'Daily',
    description: 'Triggers once every day at midnight (00:00).',
    example: 'Runs at 00:00 on Monday, 00:00 on Tuesday, etc.',
    note: 'Equivalent to the cron expression: 0 0 * * *'
  },
  Weekly: {
    title: 'Weekly',
    description: 'Triggers once every week on Sunday at midnight (00:00).',
    example: 'Runs at 00:00 every Sunday.',
    note: 'Equivalent to the cron expression: 0 0 * * 0'
  },
  Monthly: {
    title: 'Monthly',
    description: 'Triggers once a month on the 1st day of the month at midnight (00:00).',
    example: 'Runs at 00:00 on January 1st, February 1st, March 1st, etc.',
    note: 'Equivalent to the cron expression: 0 0 1 * *'
  },
  Yearly: {
    title: 'Yearly',
    description: 'Triggers once a year on January 1st at midnight (00:00).',
    example: 'Runs at 00:00 on January 1st every year.',
    note: 'Equivalent to the cron expression: 0 0 1 1 *'
  }
};

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
  } else if (currentFrequency && FREQUENCY_EXPLANATIONS[currentFrequency]) {
    entries.push({
      id: 'spiffworkflow-frequencyExplanation',
      element,
      component: FrequencyExplanationComponent,
      frequency: currentFrequency
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

  const cronAsciiHelp = `*  *  *  *  *
┬  ┬  ┬  ┬  ┬
│  │  │  │  └ day of week (0-6, 0=Sun)
│  │  │  └─── month (1-12)
│  │  └────── day of month (1-31)
│  └───────── hour (0-23)
└──────────── minute (0-59)

---

*  - Any value
/  - Step values`;

  const descriptionNode = h('div', { style: 'margin-top: 4px;' }, [
    h('div', { style: 'margin-bottom: 8px;' }, [
      translate('To learn more about Cron formats, visit '),
      h('a', { 
        href: 'https://crontab.guru/', 
        target: '_blank', 
        style: 'color: var(--color-blue-600); text-decoration: underline;'
      }, 'crontab.guru')
    ]),
    h('pre', {
      style: 'font-family: monospace; font-size: 11px; color: #6b7280; white-space: pre; background: #f3f4f6; padding: 8px; border-radius: 4px; line-height: 1.4; margin: 0;'
    }, cronAsciiHelp)
  ]);

  return h(TextFieldEntry, {
    element,
    id,
    debounce,
    getValue,
    setValue,
    label: translate('Cron Expression'),
    description: descriptionNode
  });
}

function FrequencyExplanationComponent(props) {
  const { id, frequency } = props;
  const translate = useService('translate');

  const info = FREQUENCY_EXPLANATIONS[frequency];
  if (!info) return null;

  return h('div', {
    class: 'bio-properties-panel-entry',
    'data-entry-id': id
  }, [
    h('div', { class: 'frequency-explanation' }, [
      h('div', { class: 'frequency-explanation__card' }, [
        h('div', { class: 'frequency-explanation__title' }, translate(info.title)),
        h('div', { class: 'frequency-explanation__desc' }, translate(info.description)),
        h('div', { class: 'frequency-explanation__desc' }, [
          h('span', { class: 'frequency-explanation__label' }, translate('Example:')),
          ' ',
          translate(info.example)
        ]),
        h('div', { class: 'frequency-explanation__note' }, translate(info.note))
      ])
    ])
  ]);
}
