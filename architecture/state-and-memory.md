# State and memory

Two stores, on purpose.

## Workflow state (`workspace/state.db`)

One JSON object per run, saved after every node:

```
run_id, issue_id, bug_report, mode, status, next
spec                 triage output
repro                reproduced?, failing output, screenshots
repro_tests          repro test files the agent wrote
root_cause, relevant_files, diagnosis
attempt_count, max_attempts, feedback (evidence fed into the next repair)
test_results         every deterministic check with output
review               reviewer verdict
patch_path, files_changed, lines_changed
hidden_pass, verified, regression     benchmark scoring
usage, cost_usd, tool_calls, duration_s
approval_status
```

If the process dies mid-run, `mobileforge resume <run_id>` loads the latest checkpoint. The node that crashed never advanced `next`, so it re-runs from its start.

## Fix memory (`workspace/memory.db`, or one file per benchmark trial)

Structured records: case, category, component, bug report, root cause, verified diff, files, validation, source.

A record is written only when:
- a benchmark run's patch passed the hidden acceptance tests and the reviewer approved it, or
- a human ran `mobileforge approve` on an ad-hoc run.

Retrieval is a category filter plus a small TF-IDF score, so there's no embedding service to run. The diagnose agent gets the top matches up front and can also query memory as a tool. During the benchmark, a case can never retrieve its own earlier fix, and every trial starts with empty memory so trials stay independent.
