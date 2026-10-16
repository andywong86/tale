# Tale

Tale discovers tasks from `~/.config/tale/*.toml` and runs due tasks on demand.

Example `~/.config/tale/tasks.toml`:

```toml
[backup]
cmd = "rsync -a ./data /backup"
dir = "~/project"
cron = "0 2 * * *"
collapse = true

[cleanup]
cmd = "python cleanup.py"
```

`dir` defaults to the user's home directory. When `cron` is omitted, a task
is due immediately if `last_run` is absent. It runs until its first successful
execution, which sets `last_run`; subsequent invocations skip it. Failures,
skipped prompts, and dry runs do not mark it as completed. Remove `last_run`
to make it eligible again.

For tasks with an explicit `cron`, first discovery records the current time
without executing, so old schedule occurrences are not unexpectedly replayed.
Use `cron = "0 0 * * *"` for a daily task at midnight.

```sh
uv run tale                 # inspect each due task and confirm interactively
uv run tale --yes           # run all due tasks without prompting
uv run tale --dry-run       # show due tasks without running them
uv run tale backup          # consider only one task
```

With `collapse = true`, all missed schedule occurrences are collapsed into one
execution. Without it, each missed occurrence is executed. The `last_run` value is stored directly in the task's TOML file. Combined
command output is written to the task's `dir` directory.

## Development

```sh
uv sync
uv run test        # tests with coverage
uv run typecheck  # mypy
uv run format     # format code
uv run lint       # lint and apply fixes
uv run build      # run all four steps, stopping on failure
```
