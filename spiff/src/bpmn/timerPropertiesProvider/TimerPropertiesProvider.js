import { is } from 'bpmn-js/lib/util/ModelUtil';
import { getBusinessObject } from 'bpmn-js/lib/util/ModelUtil';
import { h } from 'preact';

const LOW_PRIORITY = 500;

/**
 * Injects visible description + validation into the default "Timer" group.
 * Enforces minute-level minimum granularity (no seconds).
 */
export default class TimerPropertiesProvider {
  constructor(propertiesPanel, translate) {
    propertiesPanel.registerProvider(LOW_PRIORITY, this);
    this.translate = translate;
  }

  getGroups(element) {
    return (groups) => {
      if (!is(element, 'bpmn:Event')) return groups;

      const bo = getBusinessObject(element);
      const defs = bo.eventDefinitions || [];
      const timerDef = defs.find(e => e.$type === 'bpmn:TimerEventDefinition');
      if (!timerDef) return groups;

      const timerGroup = groups.find(g => g.id === 'timer');
      if (timerGroup && timerGroup.entries) {
        timerGroup.entries.push({
          id: 'timer-type-description',
          element,
          component: TimerTypeDescription
        });
      }

      return groups;
    };
  }
}

TimerPropertiesProvider.$inject = ['propertiesPanel', 'translate'];


const DESCRIPTIONS = {
  timeDate: {
    icon: '📅',
    title: 'Time Date',
    desc: 'A specific point in time defined as ISO 8601 datetime.',
    examples: [
      { code: '2026-06-01T09:00:00Z', label: 'UTC time' },
      { code: '2026-06-01T12:00:00+03:00', label: 'UTC plus 3 hours' },
    ],
    note: 'Checked once per minute by the Frappe scheduler.',
  },
  timeDuration: {
    icon: '⏳',
    title: 'Time Duration',
    desc: 'A delay defined as ISO 8601 duration. Minimum granularity is 1 minute.',
    examples: [
      { code: 'PT5M', label: '5 minutes' },
      { code: 'PT1H30M', label: '1 hour and 30 minutes' },
      { code: 'P1D', label: '1 day' },
      { code: 'P14D', label: '14 days' },
    ],
    note: 'Seconds (e.g. PT15S) are not supported — Frappe scheduler runs at minute intervals.',
  },
  timeCycle: {
    icon: '🔄',
    title: 'Time Cycle',
    desc: 'A recurring schedule. Use cron expressions (recommended) or ISO 8601 repeating intervals.',
    examples: [
      { code: '*/5 * * * *', label: 'every 5 minutes' },
      { code: '0 9 * * *', label: 'daily at 9:00 AM' },
      { code: '0 0 * * 0', label: 'every Sunday at midnight' },
      { code: '0 0 1 * *', label: '1st of every month' },
    ],
    note: 'Minimum interval is 1 minute. Frappe scheduler does not support second-level precision.',
  },
};


/**
 * Detect if a timer value uses seconds (which Frappe doesn't support).
 * Returns an error message string if invalid, or null if OK.
 */
function validateNoSeconds(type, value) {
  if (!value || !value.trim()) return null;
  const v = value.trim();

  if (type === 'timeDuration') {
    // Pure seconds only: PT15S, PT30S — no other time components
    if (/^P(T\d+S)$/i.test(v)) {
      return `"${v}" uses seconds. Minimum supported duration is 1 minute (PT1M). Frappe scheduler only runs at minute intervals.`;
    }
    // Any duration that ends with seconds component: PT1M30S, PT1H30S, P1DT30S
    if (/\d+S\s*$/i.test(v)) {
      return `"${v}" includes a seconds component which will be ignored. Use whole minutes instead (e.g. PT2M).`;
    }
  }

  if (type === 'timeCycle') {
    // ISO 8601 repeating with seconds: R5/PT10S, R/PT30S
    if (/\/PT\d+S\s*$/i.test(v)) {
      return `"${v}" uses second-level intervals. Minimum cycle interval is 1 minute. Use cron expressions or PT1M.`;
    }
  }

  return null;
}


function TimerTypeDescription(props) {
  const { element } = props;

  const bo = getBusinessObject(element);
  const defs = bo.eventDefinitions || [];
  const timerDef = defs.find(e => e.$type === 'bpmn:TimerEventDefinition');
  if (!timerDef) return null;

  // Detect which type is selected
  let selectedType = null;
  let currentValue = '';
  if (timerDef.get('timeDate')) {
    selectedType = 'timeDate';
    const expr = timerDef.get('timeDate');
    currentValue = expr && expr.get ? (expr.get('body') || '') : '';
  } else if (timerDef.get('timeDuration')) {
    selectedType = 'timeDuration';
    const expr = timerDef.get('timeDuration');
    currentValue = expr && expr.get ? (expr.get('body') || '') : '';
  } else if (timerDef.get('timeCycle')) {
    selectedType = 'timeCycle';
    const expr = timerDef.get('timeCycle');
    currentValue = expr && expr.get ? (expr.get('body') || '') : '';
  }

  if (!selectedType) return null;

  const info = DESCRIPTIONS[selectedType];
  if (!info) return null;

  const validationError = validateNoSeconds(selectedType, currentValue);

  return h('div', {
    class: 'bio-properties-panel-entry bpmn-timer-description-entry',
  }, [
    // Validation error banner
    validationError ? h('div', {
      class: 'bpmn-timer-validation-error',
    }, [
      h('span', { class: 'bpmn-timer-validation-icon' }, '❌'),
      h('span', { class: 'bpmn-timer-validation-text' }, validationError),
    ]) : null,

    // Description card
    h('div', { class: 'bpmn-timer-info-card' }, [
      h('div', { class: 'bpmn-timer-info-title' },
        `${info.icon} ${info.title}`
      ),
      h('div', { class: 'bpmn-timer-info-desc' }, info.desc),
      h('div', { class: 'bpmn-timer-info-examples' },
        info.examples.map(ex =>
          h('div', { class: 'bpmn-timer-info-example', key: ex.code }, [
            h('code', { class: 'bpmn-timer-info-code' }, ex.code),
            h('span', { class: 'bpmn-timer-info-label' }, `— ${ex.label}`),
          ])
        )
      ),
      // Frappe scheduler note
      h('div', { class: 'bpmn-timer-info-note' }, [
        h('span', { class: 'bpmn-timer-info-note-icon' }, '⚠️'),
        h('span', null, info.note),
      ]),
    ])
  ]);
}
