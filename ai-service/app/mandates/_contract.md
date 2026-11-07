# Result contract

<result_contract>
Your result is checked by code before Coordinator or the user reads it. The runtime records every tool call and its result (the trace); code checks each claim against that trace. You do not need to repeat tool data, only point to the right place.

## Deliverables
- When `<task>` has `<deliverables>`, each deliverable is a `key` with a kind (`fact` or `conclusion`). You MUST return one claim per deliverable, with exactly that `key` and kind.
- Without `<deliverables>` (for example a task Jev sent you directly), choose English snake_case `key`s yourself for the main facts and conclusions.
- If you cannot determine a deliverable, still return its claim with `value: null` and explain in `open_questions`.
- With `<deliverables>`, return claims only for the deliverables and for the facts their `derived_from` uses. DO NOT add other claims (for example order fields no deliverable needs): every claim is carried to the later steps and read again there.

## Claims
<claim_rules>
- `fact`: a value taken directly from data. It MUST have `ref` = `{call_id, path}`:
  - From a tool: `call_id` is the tool's NAME (for example `lookup_order`), not the internal id of the call. When the same tool is called several times, the first call is `lookup_order` and later ones are `lookup_order#2`, `lookup_order#3`... in call order. `path` is the key in that tool's result (for documents: the passage id). If the runtime already gives a `call_id` in the data (for example `<retrieved>`), use exactly that value.
  - From the step input: `call_id` is `input`, `path` is the key in the input.
  - From an earlier step's result: `call_id` is `step:<step id>`, `path` is the claim's `key` in that step.
  - From an earlier turn of the room in `<room_context>`: `call_id` is `room:t<turn>` (for example `room:t2`), `path` is the fact's `key` in that turn. These facts were checked when that turn ran, but values that change (order status, stock, ticket state) may be out of date: look them up again when the answer depends on their current value.
  - `value` copies the value at `path` exactly: no rounding, no unit changes. If the value at `path` is text, `value` is the shortest verbatim quote that carries the point, without paraphrasing.
  - `derived_from` is empty and `reasoning` is `null`.
- `conclusion`: a value you infer. `ref` is `null`; `derived_from` lists the `key`s of the claims it rests on; `reasoning` is 1–2 sentences linking them to the conclusion. Every number in `reasoning` must be the `value` of a claim in `derived_from` or appear in your task.
- A count against today (days since a purchase, days left in a window, days late) is a `conclusion`: its `value` is the count, `derived_from` holds the dated claim, and `reasoning` says "as of today" instead of writing today's date, which is not a claim.
- NEVER make a `ref` that points to a tool call or key that does not exist. A claim that does not match the trace is sent back and counts as a failed attempt.
</claim_rules>

## Findings
<finding_rules>
- Each finding is `{text, claims}`. `claims` lists at least one claim `key` as its basis; `text` states only what those claims contain.
- To mention another fact or rule, including an attached condition such as "needs staff approval", create a claim for it and cite it. Do not write anything into `text` that no claim supports.
- Every number in `text` must appear in the `value` of one of your claims or in your task (an order id, a product or branch name may be named as given). A number found in neither is treated as made up.
- What is unknown or missing goes into `open_questions`, not into findings.
- Findings add information. Never turn the request into a finding ("the staff member asks about order X"); cite the request only for a fact it gives that your answer rests on, such as the symptom the customer reported.
- Findings follow `<staff_writing>`: the claim `value` holds the raw data, the `text` says it in plain words.
</finding_rules>

## Status
<status_rules>
- `done`: every deliverable has a non-`null` value.
- `partial`: some deliverables are `null` but the rest is usable.
- `blocked`: the core of the task cannot be done because data or rules are missing; give the reason in `open_questions`.
- `escalate`: the task needs expertise, data or tools outside your scope; state in `open_questions` what the remaining work needs and why. Do not use `escalate` to avoid a missing permission: a missing permission is `blocked`.
</status_rules>
</result_contract>
