# Security model

The LLM is treated as untrusted. It can only act through typed tools in `mobileforge/tools.py`.

- **No shell.** Processes are started only by `mobileforge/proc.py`, always with explicit argument lists, never through a shell, always with a timeout.
- **Isolation.** Each run gets its own git worktree under `workspace/runs/`. Your real Fineprint checkout is never touched. Approved patches are applied by you with `git apply`.
- **Path rules.** Every path is resolved and must stay inside the worktree. `node_modules`, `.git`, `android`, `ios`, build output, and the hidden test file are blocked for reads and writes.
- **Edit rules.** Only files under the layer's editable folders can change, only by replacing one exact, unique chunk of text, and only up to a fixed number of edits per attempt. Existing tests can't be edited, so an agent can't make the regression suite pass by weakening it.
- **Command allowlists.** Test runs accept only `test/...test.ts` paths. Maestro accepts only flow ids the case approved.
- **Hidden tests.** Acceptance tests live in `benchmark/cases/`, outside the worktree. They're copied in only after the agents finish, run once, and deleted.
- **Bounded loops.** Turn limits per agent, a max number of repair attempts, and per-command timeouts.
- **Human in the loop.** The best outcome a run can reach on its own is `awaiting_approval`.
