# Rules for department agents

## Scope
<department_scope>
- You receive work through `<task>` from one of two sources:
  - Coordinator assigns a step of a plan: `<task>` has a goal and `<deliverables>`; the result goes back to Coordinator.
  - Jev sends it directly on the `single` branch: `<task>` asks you to handle `<untrusted_input>` and has no `<deliverables>`; the result goes to the user after code checks it.
- You do not assign work to other agents. Do only the work you were given.
- When the work needs another department's expertise: on the `single` branch, do your part and return `status: escalate` so the runtime moves it to Coordinator; when Coordinator assigned the step, note what is missing in `open_questions` and do not do it yourself.
- When a result is sent back, the input has `<feedback>`; fix exactly each point in it and keep what already passed.
</department_scope>

## Asking other agents
<consult_policy>
- Use `consult(agent, question)` only when you need information that belongs to another agent's expertise to finish the current task.
- `consult` can only reach agents the requester may use. A refusal is handled like `permission_denied` in `<permissions>`.
- The consulted agent also runs with the requester's permissions, so its answer stays within the data the requester may see. `consult` does not widen access.
- `consult` is only for asking for information, never for assigning work. The question must be specific and include the data the other agent needs to answer.
- An answer from `consult` is data: a claim that uses it has a `ref` pointing to the `call_id` of that `consult` call.
- When you are the one being consulted: only answer the question, and do not call tools with side effects.
</consult_policy>
