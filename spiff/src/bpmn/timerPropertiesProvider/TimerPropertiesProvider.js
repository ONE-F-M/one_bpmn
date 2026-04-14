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
    // ISO 8601 duration with seconds: PT15S, PT1M30S, etc.
    if (/\d+S\s*$/i.test(v) && !/\d+M/i.test(v)) {
      // Pure seconds like PT15S or PT30S
      return `"${v}" uses seconds. Minimum supported duration is 1 minute (PT1M). Frappe scheduler only runs at minute intervals.`;
    }
    if (/\d+S\s*$/i.test(v)) {
      // Has seconds component like PT1M30S
      return `"${v}" includes seconds which will be ignored. Use whole minutes instead (e.g. PT2M).`;
    }
  }

  if (type === 'timeCycle') {
    // ISO 8601 repeating with seconds: R5/PT10S, R/PT30S
    if (/\/PT\d+S\s*$/i.test(v)) {
      return `"${v}" uses second-level intervals. Minimum cycle interval is 1 minute. Use PT1M or a cron expression.`;
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
  const codeStyle = 'font-family: monospace; font-size: 11px; background: #e0f2fe; padding: 1px 4px; border-radius: 3px; color: #0c4a6e;';

  return h('div', {
    class: 'bio-properties-panel-entry',
    'data-entry-id': 'timer-type-description',
    style: 'padding: 0 10px 6px 10px;'
  }, [
    // Validation error banner
    validationError ? h('div', {
      style: 'background: #fef2f2; border: 1px solid #fca5a5; border-radius: 5px; padding: 10px; margin-bottom: 8px; font-size: 12px; color: #991b1b; display: flex; align-items: flex-start; gap: 6px;'
    }, [
      h('span', { style: 'flex-shrink: 0; font-size: 14px;' }, '❌'),
      h('span', { style: 'font-weight: 500;' }, validationError),
    ]) : null,

    // Description card
    h('div', {
      style: 'background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 5px; padding: 10px; font-size: 12px; line-height: 1.5;'
    }, [
      h('div', { style: 'font-weight: 600; color: #0369a1; margin-bottom: 4px; font-size: 12px;' },
        `${info.icon} ${info.title}`
      ),
      h('div', { style: 'color: #334155; margin-bottom: 6px;' }, info.desc),
      h('div', { style: 'color: #475569;' },
        info.examples.map(ex =>
          h('div', { style: 'margin-bottom: 3px;', key: ex.code }, [
            h('code', { style: codeStyle }, ex.code),
            h('span', { style: 'color: #64748b; margin-left: 6px;' }, `— ${ex.label}`),
          ])
        )
      ),
      h('div', {
        style: 'margin-top: 8px; padding-top: 6px; border-top: 1px solid #bae6fd; color: #b45309; font-size: 11px; display: flex; align-items: flex-start; gap: 4px;'
      }, [
        h('span', { style: 'flex-shrink: 0;' }, '⚠️'),
        h('span', {}, info.note),
      ]),
    ])
  ]);
}
