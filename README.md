# Tale

Tale discovers tasks from `~/.config/tale/*.toml` and runs due tasks on demand.

Example `~/.config/tale/tasks.toml`:

```toml
[backup]
cmd = "rsync -a ./data /backup"
dir = "~/project"
cron = "0 2 * * *"
collapse = true

[sync]
cmd = "python sync.py"
interval = "6h"

[cleanup]
cmd = "python cleanup.py"
```

`dir` defaults to the user's home directory. When both `cron` and `interval`
are omitted, a task
is due immediately if `last_run` is absent. It runs until its first successful
execution, which sets `last_run`; subsequent invocations skip it. Failures,
skipped prompts, and dry runs do not mark it as completed. Remove `last_run`
to make it eligible again.

For tasks with an explicit `cron`, first discovery records the current time
without executing, so old schedule occurrences are not unexpectedly replayed.
Use `cron = "0 0 * * *"` for a daily task at midnight.

Interval tasks are due immediately on first discovery. After that, each elapsed
interval since `last_run` is a missed occurrence. With the default
`collapse = true`, they execute once for the latest missed boundary; with
`collapse = false`, they execute each missed boundary in order. Successful runs
advance `last_run` to the scheduled boundary, not the completion time. A failed
run stops catch-up without advancing progress for that occurrence, leaving it
and subsequent occurrences pending for retry. For example, a one-minute interval
with ten minutes elapsed runs once by default, or ten times with `collapse = false`.
Tale only checks tasks when invoked, not continuously.

Use positive whole numbers with lowercase units `s`, `m`, `h`, `d`, or `w`,
for example `"30m"`, `"6h"`, `"1h30m"`, or `"1h 30m"`. Days and weeks are fixed
24-hour and 7-day durations. Bare numbers, decimals, repeated units, unknown
units, and zero or negative components are rejected. `cron` and `interval`
cannot be specified together.

```sh
uv run tale                 # inspect each due task and confirm interactively
uv run tale --yes           # run all due tasks without prompting
uv run tale --dry-run       # show due tasks without running them
uv run tale backup          # consider only one task
```

`collapse` defaults to `true`: all missed cron or interval occurrences are collapsed
into one execution. Set `collapse = false` to execute each missed occurrence. The `last_run` value is stored directly in the task's TOML file. Combined
command output is written to a unique log file in the task's `dir` directory
for each execution, including catch-up runs.

Tale exits with `1` if any task command fails or configuration/scheduling errors
occur, and `0` otherwise (including when nothing is due or tasks are skipped).
A failed command stops that task's catch-up runs without advancing `last_run`
for the failed occurrence; other due tasks are still processed.

## Environment variables

Tasks inherit Tale's environment. Add an `env` table to override or add variables
for an individual task:

```toml
[backup]
cmd = "python backup.py"

[backup.env]
BACKUP_DIR = "/mnt/backup"
LOG_LEVEL = "info"
```

An inline table is also supported: `env = { LOG_LEVEL = "info" }` inside the task.
All values must be strings (quote numbers and booleans). Empty strings are valid.
Names must be non-empty and contain neither `=` nor NUL; values cannot contain
NUL. Overrides do not change Tale's environment or affect other tasks.

Values are passed literally: `"$HOME/backup"` is not expanded automatically.
The command's shell can reference variables normally, for example
`cmd = 'python backup.py --destination "$BACKUP_DIR"'`.

Tale does not include `env` values in log metadata or task previews, but commands
can expose them through their own output. Values are stored as plain text in the
TOML file; prefer inheriting sensitive variables from Tale's environment. Inline
assignments in `cmd` are logged as part of the command, so avoid secrets there.

## Execution windows

All task types accept optional `not_before` and `not_after` bounds:

```toml
[seasonal_sync]
cmd = "python sync.py"
interval = "6h"
not_before = 2026-11-01
not_after = 2026-11-30

[precise_job]
cmd = "python job.py"
not_before = 2026-11-01T09:00:00Z
not_after = 2026-11-30T17:00:00+08:00
```

Native TOML dates and offset timestamps, or their quoted equivalents, are accepted.
Dates must use `YYYY-MM-DD`. Timestamps must include seconds and `Z` or an explicit
`+HH:MM`/`-HH:MM` offset; fractional seconds are optional. Local timestamps without
an offset, time-only values, and contradictory bounds are configuration errors.

Date-only bounds use the machine's local timezone: `not_before` includes local
midnight, and `not_after` includes the entire day (excluding the following
midnight). Timestamp bounds are inclusive. Equal date bounds allow that entire
day; equal timestamp bounds allow only that instant.

| Bounds | Single execution | Cron | Interval |
| --- | --- | --- | --- |
| Neither | Due until successful | Normal cron behavior | Normal interval behavior |
| `not_before` | Due at/after the bound | Only occurrences at/after the bound | First occurrence anchored to the bound if never run |
| `not_after` | Due until the deadline | No execution after the deadline | No execution after the deadline |
| Both | Execute once within the window | Eligible occurrences within the window | Start/repeat within the window |

For existing interval tasks, their interval phase is preserved; occurrences before
`not_before` are ignored. For never-run interval tasks with `not_before`, the first
occurrence is at that bound, even if discovered later; subsequent intervals catch
up according to `collapse`. Cron tasks still initialize without replaying history
on their first discovery within the window. First discovery outside the window
does not initialize `last_run`.

Occurrences are filtered before applying `collapse`. Once `not_after` has passed,
even previously missed occurrences cannot run. The window is rechecked before
every execution, including after confirmation and between catch-up runs. A command
started inside the window may finish after the deadline; it is not terminated.
Blocked or expired tasks do not advance `last_run`. As always, tasks only run when
Tale is invoked.

## Development

```sh
uv sync
uv run test        # tests with coverage
uv run typecheck  # mypy
uv run format     # format code
uv run lint       # lint and apply fixes
uv run build      # run all four steps, stopping on failure
```
