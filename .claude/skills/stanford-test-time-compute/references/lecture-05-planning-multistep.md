# Part 5 — Planning and Multi-Step Reasoning

Video: <https://www.youtube.com/watch?v=Ml_fp9XkB8Y>

Recorded 2025-10-06; published 2026-08-03. Duration 74:55.

## Timeline

| Time | Argument |
|---|---|
| 00:00–23:29 | LATS combines ReAct with Monte Carlo Tree Search over alternative action trajectories. |
| 23:29–50:25 | SPRINT learns independent plans that can be executed in parallel and merged. |
| 50:25–74:55 | SWiRL creates synthetic multi-step tool trajectories and trains with step-wise RL. |

## LATS — retain alternatives

LATS turns a single ReAct path into a tree. It uses selection, expansion,
evaluation, simulation, and backpropagation to explore several action
sequences. LLM judges, self-consistency, and environment reward estimate node
value.

Use tree search when:

- early choices create materially different futures;
- the environment allows rollback or simulation;
- candidate paths can be scored before committing;
- the expected gain justifies repeated model and tool calls.

Avoid it when actions are irreversible, the judge is weaker than the branching
policy, or state cloning is inaccurate. A large tree over a bad simulator
creates confident fiction.

## SPRINT — parallelize independent subplans

SPRINT observes that not every reasoning step depends on the previous token
sequence. It fine-tunes a planner to emit independent plans, executes them
concurrently, and uses an evaluator to integrate the results.

Its gains should be read on two axes:

- accuracy or task success;
- sequential token depth and wall-clock latency.

Parallel generation is useful only when subplans are genuinely independent.
Shared mutable state, duplicated work, and inconsistent assumptions can erase
the speedup.

## SWiRL — learn multi-step behavior from synthetic trajectories

SWiRL constructs synthetic multi-step tool-use trajectories, scores and filters
them with a model judge, then performs step-wise reinforcement learning. The
training phase does not need to execute real tools for every update because it
learns from collected trajectories.

Its design separates:

1. Synthetic data collection.
2. Trajectory filtering.
3. Step-wise RL.
4. Multi-step inference.

The filtering result matters as much as dataset scale. Low-quality synthetic
traces can teach plausible but incorrect action transitions.

## Planning decision table

| Need | Operator | Evidence required |
|---|---|---|
| One bounded next action | ReAct | tool result and stop condition |
| Several uncertain futures | LATS / tree search | cloneable state and path evaluator |
| Independent subtasks | planner + parallel executor | dependency graph and merge contract |
| Repeated task family | synthetic trajectories + RL | reliable step/outcome reward and held-out tasks |

## Runtime implication

Planning is not a prose field. Represent plan identity, dependencies, action
state, observations, retry lineage, and terminal reason. Otherwise the system
cannot determine whether a failure came from decomposition, execution, merging,
or verification.
