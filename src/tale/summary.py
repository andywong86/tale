from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionSummary:
    """Separate task outcomes from individual catch-up command outcomes."""

    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    deferred: int = 0
    not_due: int = 0
    errors: int = 0
    executions_succeeded: int = 0
    executions_failed: int = 0
    executions_not_run: int = 0

    def record_results(self, planned: int, results: list[int]) -> None:
        failures = sum(code != 0 for code in results)
        self.executions_succeeded += len(results) - failures
        self.executions_failed += failures
        self.executions_not_run -= len(results)
        if failures:
            self.failed += 1
        elif len(results) == planned:
            self.succeeded += 1
        else:
            # A window may close after confirmation or between catch-up runs.
            self.deferred += 1

    def print(self) -> None:
        print()
        print(
            f"Summary (tasks): {self.succeeded} succeeded, {self.failed} failed, "
            f"{self.skipped} skipped, {self.deferred} deferred, {self.not_due} not due; "
            f"{self.errors} errors."
        )
        print(
            f"Executions: {self.executions_succeeded} succeeded, "
            f"{self.executions_failed} failed, {self.executions_not_run} not run."
        )
