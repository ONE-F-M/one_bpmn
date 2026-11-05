# Which queue runs what, and why it matters

WI-002055. Written down because it was not: until this was measured, nobody could
say whether `poll_a2a_tasks` competed with unrelated long-running jobs, and the
answer turned out to be yes.

## The jobs with a clock attached

Three scheduled jobs are the ones something is *waiting on*. Their lateness is
visible to a person as "why hasn't this happened yet":

| job | what it notices |
|---|---|
| `one_bpmn.tasks.poll_a2a_tasks` | a delegated worker finished; a deadline passed; a retry is due |
| `one_bpmn.tasks.process_timer_catch_events` | a waiting instance's timer elapsed |
| `one_bpmn.tasks.process_timer_start_events` | a timed process should start now |

All three run `* * * * *`.

## How Frappe picks a queue, and why that was the problem

`ScheduledJobType.get_queue_name()` derives the queue from the **frequency alone**:

```python
return "long" if ("Long" in self.frequency or "Maintenance" in self.frequency) else "default"
```

A `Cron` job therefore always lands on **`default`**. There is no per-job setting.

Measured on the development bench, 2026-08-24:

- **172 enabled scheduled jobs** land on `default`, out of 248 total — plus every
  `enqueue()` the rest of the application makes.
- One worker (`bench worker`, no `--queue`) serves **short, default and long**
  together. `background_workers = 1`.
- Gaps between consecutive `poll_a2a_tasks` runs: **median 76s** against a
  60-second schedule, **worst 4,058s**. Four gaps over three minutes in the last
  forty runs.

A worst gap of 4,058 seconds means a delegation could finish and go **sixty-eight
minutes** before anything noticed.

The precedent for the fix was already in the Procfile: agent **turns** were given
their own worker (`bpmn_ai_agent`) so a long LLM call would not queue behind
somebody's bulk import. The jobs that *wake* those turns had no such protection.

## What this change does

`one_bpmn/overrides/scheduled_job_type.py` overrides `get_queue_name()` for those
three methods only, returning `bpmn_clock`. Every other scheduled job on the site
— Frappe's, ERPNext's, one_fm's — falls through to the original behaviour.

**It degrades to today's behaviour by design.** The dedicated queue is claimed
only when the site actually declares it in `common_site_config.json`; otherwise
the jobs stay on `default`. A queue nothing consumes is a black hole, and
enqueueing into one would turn a delay into a permanent stall. So the code is safe
to deploy before, after, or without the worker configuration.

## Enabling it on an environment

Two changes, both outside the app.

**1. Declare the queue** in `sites/common_site_config.json`:

```json
"workers": {
    "bpmn_ai_agent": { "timeout": 600 },
    "bpmn_clock":    { "timeout": 300 }
}
```

300s is deliberate: these jobs should take seconds. A clock job that runs for five
minutes is broken, and a short timeout says so instead of hiding it.

**2. Run a worker for it.**

Development (`Procfile`):

```
bpmn_clock_worker: bench worker --queue bpmn_clock 1>> logs/bpmn_clock.log 2>> logs/bpmn_clock.error.log
```

Production (supervisor): add a program consuming `bpmn_clock` alongside the
existing `bpmn_ai_agent` one. Regenerate with `bench setup supervisor` if the
config is generated rather than hand-maintained.

Verify with the A2A screen, or:

```python
frappe.get_doc("Scheduled Job Type", "tasks.poll_a2a_tasks").get_queue_name()
# -> "bpmn_clock" once the queue is declared, "default" before
```

## Telling the three failures apart

A starved reconciler, a stopped job, and a hung agent all look the same from the
delegation list: things sitting in Working. `one_bpmn/agents/a2a/reconciler_health.py`
names the cause instead, and the A2A screen shows it above the lists it explains:

| state | what it means |
|---|---|
| `running` | on schedule; the banner is hidden |
| `scheduler_disabled` | the whole site's scheduler is off — **`bench migrate` turns it off at the start and on at the end, so an interrupted or failing migrate leaves it off** |
| `job_stopped` | this job alone was stopped by hand |
| `queue_backlog` | enqueued and waiting behind other work — the starvation case |
| `no_worker` | nothing is consuming its queue |
| `late_unexplained` | none of the above; the job itself is erroring or slow |

The first of those is not hypothetical. It is the state this bench was found in
while writing this: every cron job's last execution stamped the same second,
hours earlier, because a migrate had failed part-way through — and the visible
symptom was "delegations look stuck".

## Environments

| environment | status |
|---|---|
| development (this bench) | measured above; needs both steps applied |
| staging / BA site | **not yet examined** — the queue configuration is not in this repo, so it has to be read on the host |
| production | **not yet examined** — same |

Applying the two steps to staging and production is deployment work, not a code
change, and is left for whoever administers those hosts. The code is already safe
there: without the declaration the jobs behave exactly as they do today.
