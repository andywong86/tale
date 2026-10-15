# Tale

Tale discovers tasks from `~/.config/tale/*.toml` and runs due tasks on demand.

Example `~/.config/tale/tasks.toml`:

```toml
[backup]
cmd = "rsync -a ./data /backup"
dir = "~/project"
cron = "0 2 * * *"
once = true

[cleanup]
cmd = "python cleanup.py"
```

`dir` defaults to the user's home directory and `cron` defaults to once daily
(`0 0 * * *`). On first discovery, a task's current time is recorded so old
schedule occurrences are not unexpectedly replayed.

```sh
uv run tale                 # inspect each due task and confirm interactively
uv run tale --yes           # run all due tasks without prompting
uv run tale --dry-run       # show due tasks without running them
uv run tale backup          # consider only one task
```

With `once = true`, all missed schedule occurrences are collapsed into one
execution. Without it, each missed occurrence is executed. The `last_run` value is stored directly in the task's TOML file. Combined
command output is written to the task's `dir` directory.
