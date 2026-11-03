# Agent graph

The orchestrator (`mobileforge/orchestrator.py`) is an explicit state machine. Each node reads and writes one shared state object and returns the name of the next node.

| Node | Kind | Next |
| --- | --- | --- |
| triage | agent | reproduce |
| reproduce | agent + deterministic re-run | diagnose, or finalize with `needs_info` |
| diagnose | agent | repair |
| repair | agent | verify |
| verify | deterministic | review, repair (attempts left), or finalize with `failed` |
| review | agent | finalize with `awaiting_approval`, repair, or finalize with `rejected_by_review` |
| finalize | deterministic | done |

Single-agent baseline mode runs `single -> finalize` with the same verification gate.

Why a hand-written state machine instead of a framework: the graph is small, every transition is easy to test, and checkpoint/resume is about 40 lines of SQLite. The node functions would port directly to LangGraph nodes if that's ever useful.

Each agent must finish by calling a `submit` tool whose input schema is the agent's output contract. On its last allowed turn the model is forced to call `submit`, so an agent can run out of turns but never hang.
