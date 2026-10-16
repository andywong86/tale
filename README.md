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

Interval tasks are due immediately on first discovery, then when at least the
specified duration has elapsed since their last successful completion. Success
sets `last_run` to the actual completion time; failures leave it unchanged.
They run once per invocation, with no catch-up runs (`collapse` has no effect).
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

With `collapse = true`, all missed schedule occurrences are collapsed into one
execution. Without it, each missed occurrence is executed. The `last_run` value is stored directly in the task's TOML file. Combined
command output is written to a unique log file in the task's `dir` directory
for each execution, including catch-up runs.

Tale exits with `1` if any task command fails or configuration/scheduling errors
occur, and `0` otherwise (including when nothing is due or tasks are skipped).
A failed command stops that task's catch-up runs without advancing `last_run`
for the failed occurrence; other due tasks are still processed.

## Development

```sh
uv sync
uv run test        # tests with coverage
uv run typecheck  # mypy
uv run format     # format code
uv run lint       # lint and apply fixes
uv run build      # run all four steps, stopping on failure
```
