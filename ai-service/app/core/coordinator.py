"""Coordinator runtime: plan → run each step → review → finalize (PLAN-lite §7, hub-and-spoke).

The model plans and reviews; code makes sure every decision is one the runtime can carry out before
acting on it: the plan is a DAG over agents the requester may use, and each decision sets the field
the decision table in `coordinator.md` requires. A failed check goes back to the model through the
`AgentLoop` verify hook, so it fixes the decision in the same run.

Code also owns the counters the model must not: each step may be retried `MAX_STEP_RETRIES` times
(D-09), fewer when code rejects it twice for the same reason, and the whole plan replanned
`MAX_REPLANS` times. A replan keeps the steps already accepted and plans only the rest.

Steps run as a DAG: every step whose dependencies are accepted starts, at most `MAX_PARALLEL_STEPS`
at a time, so how many agents work at once is what the plan makes independent. Every result comes
back here, is checked by code, then reviewed, before a step that depends on it starts. A step that
fails does not stop the others: only the steps that depend on it are skipped, and finalize reports
what was done and what was not.
"""

import asyncio
import copy
import json
import time
from collections.abc import Awaitable, Callable, Collection, Iterable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from graphlib import CycleError, TopologicalSorter
from typing import Any

from app.core.agent.loop import FINAL_ANSWER, RunFinished
from app.core.contract import verifier
from app.core.llm.messages import AssistantMessage, Message, SystemMessage, ToolResultMessage, UserMessage
from app.core.llm.types import Usage
from app.mandates import Mandate

MAX_STEP_RETRIES = 4
MAX_REPLANS = 1
MAX_CLARIFY_ROUNDS = 2
# Origins where no agent fits the request: the user is asked once before a new agent is requested
CLARIFY_FIRST = ("unknown",)
# Steps running at the same time; the plan decides how many of them are independent
MAX_PARALLEL_STEPS = 3
# How a worker run ends when the model or its provider is failing: another attempt or a new plan
# would fail the same way, so the step fails at once instead of spending the retry budget
PROVIDER_FAILURES = (
    "model call failed",
    f"model ended without calling {FINAL_ANSWER}",
    "model stream ended",
    "cut off at max_tokens",
    "model stopped for an unexpected reason",
)

CHECKPOINT_VERSION = 1

Verify = Callable[[dict[str, Any], Sequence[Message]], str | None]
# Runs one agent to the end: (mandate, messages, verify hook) → its RunFinished
RunAgent = Callable[[Mandate, list[Message], Verify], Awaitable[RunFinished]]
# Receives the run's milestones as they happen (event name, data): `phase`, `plan`, `step_started`,
# `step_done` (the agent's answer passed code, before review), `step_reviewed` (the Coordinator's
# decision on it, with a note for staff), `step_accepted`, `step_failed`, `step_skipped`, so a client
# can show who works on what
OnEvent = Callable[[str, dict[str, Any]], None]
# The step the running code belongs to, set inside each step's own task, so the events of steps
# running at the same time are told apart
current_step: ContextVar[str | None] = ContextVar("current_step", default=None)


def _ignore(event: str, data: dict[str, Any]) -> None:
    pass


def today_block(today: date) -> str:
    """The date the request is handled on, set by the runtime: models never know it on their own."""
    return f"<today>\n{today.isoformat()}. Count every deadline and period from this date; do not ask for it.\n</today>"


# coordinator.md <decision_table>: phase → decision → the field that must have a value
DECISIONS: dict[str, dict[str, str | None]] = {
    "plan": {"plan": "plan", "clarify": "clarify_question", "request_agent": "agent_request",
             "cannot_complete": "final_response"},
    "review": {"accept": None, "retry": "feedback", "replan": "feedback", "clarify": "clarify_question"},
    "finalize": {"complete": "final_response", "partial": "final_response", "cannot_complete": "final_response"},
}


def check_decision(result: dict[str, Any], phase: str) -> list[str]:
    """Problems with `result` as a decision of `phase`; empty when the runtime can act on it."""
    if result.get("phase") != phase:
        return [f"phase must be '{phase}', got {result.get('phase')!r}"]
    allowed = DECISIONS[phase]
    decision = result.get("decision")
    if decision not in allowed:
        return [f"decision {decision!r} is not allowed in phase '{phase}' (allowed: {', '.join(allowed)})"]
    field = allowed[decision]
    value = result.get(field) if field else None
    if field and (value is None or (isinstance(value, str) and not value.strip())):
        return [f"decision '{decision}' needs a value in '{field}'"]
    return []


def check_plan(plan: dict[str, Any], catalog: Collection[str], unavailable: Collection[str] = (),
               kept: Collection[str] = ()) -> list[str]:
    """Problems with `plan` as a DAG the runtime can run with the agents in `catalog`.

    `unavailable` names agents that exist but the requester may not use, so the model is told the
    part needs a permission instead of being left to look for a substitute. `kept` are ids of steps
    accepted under a dropped plan: a new step may depend on them but not reuse their ids.
    """
    steps = plan.get("steps") or []
    if not steps:
        return ["the plan has no steps"]
    found: list[str] = []
    ids = [step["id"] for step in steps]
    for step_id in sorted({i for i in ids if ids.count(i) > 1}):
        found.append(f"step id '{step_id}' is used by more than one step")
    for step_id in sorted(set(ids) & set(kept)):
        found.append(f"step id '{step_id}' is a kept step in <kept_results>; plan only the remaining work, "
                     "under new ids")
    for step in steps:
        if step["agent"] in unavailable:
            found.append(f"step '{step['id']}': the user has no permission to use agent '{step['agent']}'; "
                         "leave that part out of the plan and state the missing permission when finalizing")
        elif step["agent"] not in catalog:
            found.append(f"step '{step['id']}': agent '{step['agent']}' is not in <agent_catalog>")
        for dep in step["depends_on"]:
            if dep == step["id"]:
                found.append(f"step '{step['id']}' depends on itself")
            elif dep not in ids and dep not in kept:
                found.append(f"step '{step['id']}' depends on unknown step '{dep}'")
        keys = [d["key"] for d in step["deliverables"]]
        for key in sorted({k for k in keys if keys.count(k) > 1}):
            found.append(f"step '{step['id']}': deliverable key '{key}' is declared more than once")
    if found:
        return found
    try:
        tuple(TopologicalSorter({step["id"]: step["depends_on"] for step in steps}).static_order())
    except CycleError as e:
        return [f"depends_on has a cycle: {' -> '.join(e.args[1])}"]
    return []


def _unfinished(record: dict[str, Any]) -> bool:
    """An accepted step whose own result says it did not finish (`partial`, `blocked`, `escalate`)."""
    return record["status"] == "accepted" and (record.get("result") or {}).get("status", "done") != "done"


def finalize_decisions(records: Sequence[dict[str, Any]], kept: int = 0) -> tuple[str, ...]:
    """The finalize decisions the step records allow: a part that failed is never reported as complete.

    `kept` counts steps accepted under a dropped plan, which count as done. An accepted step whose own
    result says it did not finish (`partial`, `blocked`, `escalate`) is not done either.
    """
    if not kept and not any(record["status"] == "accepted" for record in records):
        return ("cannot_complete",)
    if any(record["status"] != "accepted" or _unfinished(record) for record in records):
        return ("partial", "cannot_complete")
    return ("complete", "cannot_complete")


def decision_verifier(
    phase: str, catalog: Collection[str], unavailable: Collection[str] = (), clarify_rounds_used: int = 0,
    kept: Collection[str] = (), allowed: Collection[str] | None = None, clarify_first: bool = False,
) -> Callable[[dict[str, Any], Sequence[Message]], str | None]:
    """The `verify` hook of the Coordinator's `AgentLoop` for one phase; `allowed` narrows its decisions.

    `clarify_first`: no agent fits the request, so the user is asked once before a new agent is requested.
    """

    def verify(result: dict[str, Any], history: Sequence[Message]) -> str | None:
        problems = check_decision(result, phase)
        if not problems and allowed is not None and result["decision"] not in allowed:
            problems = [f"decision '{result['decision']}' does not match the step results "
                        f"(allowed: {', '.join(allowed)}); see <failed_steps>"]
        if not problems and result["decision"] == "plan":
            problems = check_plan(result["plan"], catalog, unavailable, kept)
        if not problems and result["decision"] == "clarify" and clarify_rounds_used >= MAX_CLARIFY_ROUNDS:
            problems = [f"no clarification rounds remain ({clarify_rounds_used} of {MAX_CLARIFY_ROUNDS} used); "
                        "work with what is known and state what is missing"]
        if not problems and result["decision"] == "request_agent" and clarify_first and clarify_rounds_used == 0:
            problems = ["<origin> is unknown: ask the user one clarify question about the work and the result "
                        "they need before requesting a new agent"]
        return "\n".join(f"- {problem}" for problem in problems) if problems else None

    return verify


class CoordinatorError(RuntimeError):
    """The Coordinator model itself could not reach a valid decision.

    `checkpoint` is where the run stood (None when it failed before any plan), so it can be resumed.
    """

    def __init__(self, message: str, checkpoint: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint


@dataclass
class Outcome:
    # The decision the run ended on: complete | partial | cannot_complete | clarify | request_agent
    decision: str
    # Text for the staff member: final response, clarify question or why the run stopped
    output: str
    plan: dict[str, Any] | None = None
    agent_request: dict[str, Any] | None = None
    # One record per step of the last plan that ran (steps kept from a dropped plan are in `replans`):
    # id, agent, status, attempts, rejections, result, reason, seconds, answers ({result, seconds, review});
    # status is accepted | failed (out of attempts, or its model could not run) | skipped (a step it
    # depends on did not succeed) | clarify (its review asked the user); `reason` says why a step failed
    # or was skipped, and each rejection is {attempt, by: code | coordinator, reason}
    steps: list[dict[str, Any]] = field(default_factory=list)
    # Plans dropped by a replan, each with the failure that caused it and its step records
    replans: list[dict[str, Any]] = field(default_factory=list)
    # High-risk calls of accepted steps, each tagged with its step id; none ran
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    # Summed over every Coordinator and worker run
    usage: Usage = field(default_factory=Usage)
    model_steps: int = 0


@dataclass
class _Execution:
    """How running a plan ended: all steps accepted, some failed, a replan asked for, or the user must answer."""

    records: list[dict[str, Any]]
    accepted: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    # A review asked for a new plan: no new step starts
    replan: str | None = None
    # Steps that failed in a way a new plan may avoid (out of attempts, the same rejection twice);
    # the other steps go on
    failures: list[str] = field(default_factory=list)
    clarify: dict[str, Any] | None = None

    @property
    def stopped(self) -> bool:
        """A review asked for a replan or a question to the user: start no new step."""
        return self.replan is not None or self.clarify is not None

    @property
    def failure(self) -> str | None:
        """Why the plan should be redone, or None when nothing a new plan could fix went wrong."""
        return self.replan or "\n".join(self.failures) or None


class Coordinator:
    def __init__(self, mandate: Mandate, catalog: Sequence[Mandate], run_agent: RunAgent, today: date,
                 unavailable: Sequence[Mandate] = (), on_event: OnEvent = _ignore,
                 room: str = "", room_sources: dict[str, dict[str, Any]] | None = None) -> None:
        # `catalog` holds only the agents the requester may use: a plan can name nothing else.
        # `unavailable` are the agents they may not use, shown so a missing permission is reported
        # as one, never worked around through another agent or a new one.
        # `room` is the `<room_context>` block of earlier turns (empty on a room's first request), and
        # `room_sources` its facts, citable by every step.
        self._room = room
        self._room_sources = room_sources or {}
        self._mandate = mandate
        self._agents = {agent.name: agent for agent in catalog}
        self._unavailable = {agent.name: agent for agent in unavailable}
        self._run_agent = run_agent
        self._emit = on_event
        self._today = today_block(today)
        self._text = ""
        self._clarifications: list[dict[str, str]] = []
        self._clarify_first = False
        self._replans: list[dict[str, Any]] = []
        # Steps accepted under a plan that was dropped, by id: {agent, result, pending_actions}. A
        # replan covers only the rest, so work that already passed is not paid for twice.
        self._kept: dict[str, dict[str, Any]] = {}
        self._usage = Usage()
        self._model_steps = 0

        # What a checkpoint needs: the plan that is running, its replan count and why it was made, the
        # execution so far, and the steps whose answer passed code but whose review has not answered yet
        self._plan: dict[str, Any] | None = None
        self._attempt = 0
        self._failure: str | None = None
        self._execution: _Execution | None = None
        self._awaiting_review: dict[str, dict[str, Any]] = {}
        self._escalated: dict[str, Any] = {}

    async def run(self, text: str, origin: str, escalation: dict[str, Any] | None = None,
                  clarifications: Sequence[dict[str, str]] = (), notes: dict[str, Any] | None = None) -> Outcome:
        # `clarifications` are the earlier clarify rounds of this request: {question, answer}, oldest first.
        # `notes` are extra plan-phase blocks by name (coordinator.md <input_contract>), e.g. a new agent.
        self._text = text
        self._clarifications = list(clarifications)
        self._clarify_first = origin in CLARIFY_FIRST
        return await self._loop(text, origin, escalation, notes, 0, None, None)

    async def _execute(self, plan: dict[str, Any], can_replan: bool, prior: dict[str, Any] | None = None) -> _Execution:
        """Run the plan as a DAG: every step whose dependencies are done starts, at most
        `MAX_PARALLEL_STEPS` at a time. A failed step is recorded and the others go on; a step that
        depends on one that did not succeed is skipped. `prior` is what a resumed run already did: its
        accepted steps are not run again, and a step whose answer awaits review only gets that review. A review asking to replan or clarify starts no
        new step; the steps already running finish, so no model call is cut off halfway."""
        steps = {step["id"]: step for step in plan["steps"]}
        position = {step_id: i for i, step_id in enumerate(steps)}
        # Kept steps are already accepted: they feed the new steps and finalize but do not run again
        sorter = TopologicalSorter({s["id"]: [d for d in s["depends_on"] if d in steps] for s in plan["steps"]})
        sorter.prepare()
        execution = _Execution(records=[], accepted={i: k["result"] for i, k in self._kept.items()},
                               pending_actions=[a for k in self._kept.values() for a in k["pending_actions"]])
        prior = prior or {"accepted": {}, "awaiting_review": {}, "pending_actions": [], "records": []}
        # The checkpoint's list holds the kept steps' calls too
        execution.accepted.update(prior["accepted"])
        if prior["pending_actions"]:
            execution.pending_actions = list(prior["pending_actions"])
        done_before = {r["id"]: r for r in prior["records"]}
        self._execution = execution
        ready: list[str] = []
        running: dict[asyncio.Task[None], str] = {}
        try:
            while True:
                if not execution.stopped:
                    ready += sorter.get_ready()
                    while ready and len(running) < MAX_PARALLEL_STEPS:
                        step = steps[ready.pop(0)]
                        # `answers`: every result that passed code, in order, each with how long the agent worked
                        # on it and the Coordinator's review, so the whole exchange can be shown, redone answers included
                        awaiting = prior["awaiting_review"].get(step["id"])
                        if step["id"] in prior["accepted"] and step["id"] in done_before:
                            # Accepted before the run was cut short: its record stands, it does not run again
                            execution.records.append(copy.deepcopy(done_before[step["id"]]))
                            self._emit("step_accepted", {"id": step["id"], "agent": step["agent"],
                                                         "summary": prior["accepted"][step["id"]].get("summary"),
                                                         "seconds": done_before[step["id"]]["seconds"]})
                            sorter.done(step["id"])
                            ready += sorter.get_ready()
                            continue
                        if awaiting is not None and step["id"] in done_before:
                            # Keeps its attempts and answers; only the review is left
                            record: dict[str, Any] = copy.deepcopy(done_before[step["id"]])
                            record["status"] = "failed"
                        else:
                            awaiting = None
                            record = {"id": step["id"], "agent": step["agent"], "status": "failed",
                                      "attempts": 0, "rejections": [], "result": None, "reason": None,
                                      "seconds": 0.0, "answers": []}
                        execution.records.append(record)
                        blocked = [dep for dep in step["depends_on"] if dep not in execution.accepted]
                        if blocked:
                            record["status"] = "skipped"
                            record["reason"] = f"depends on {', '.join(map(repr, blocked))}, which did not succeed"
                            self._emit("step_skipped", {"id": step["id"], "agent": step["agent"], "reason": record["reason"]})
                            sorter.done(step["id"])
                            ready += sorter.get_ready()
                            continue
                        running[asyncio.create_task(self._run_to_end(step, record, execution, can_replan, awaiting))] = step["id"]
                if not running:
                    break
                finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in finished:
                    sorter.done(running.pop(task))
                    task.result()  # a Coordinator failure ends the run
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
        execution.records.sort(key=lambda record: position[record["id"]])
        return execution

    async def _run_to_end(self, step: dict[str, Any], record: dict[str, Any], execution: _Execution,
                          can_replan: bool, resume_final: dict[str, Any] | None = None) -> None:
        """Run one step until it is accepted or fails, retrying with feedback; runs in its own task.

        `resume_final` is an answer that passed code before a failed review: only its review is left."""
        step_id = step["id"]
        current_step.set(step_id)
        # The step's input goes out too, so the trace shows what each agent was given
        self._emit("step_started", {"id": step_id, "agent": step["agent"], "label": step["label"],
                                    "task": step["task"], "depends_on": step["depends_on"]})
        # `seconds` counts the agent's own work over every attempt; reviews are the Coordinator's time
        worked = 0.0
        worked_before = 0.0  # agent time already counted in an earlier answer

        def failed(reason: str) -> None:
            record["reason"] = reason
            self._emit("step_failed", {"id": step_id, "agent": step["agent"], "reason": reason,
                                       "seconds": record["seconds"]})

        feedback: str | None = None
        if resume_final is not None:
            # Resumed after its review failed: the answer already passed code, keep the time it took
            worked = worked_before = record["seconds"]
        for _ in range(MAX_STEP_RETRIES + 1):
            if resume_final is not None:
                final, calls = resume_final["final"], resume_final["pending_actions"]
                answer = record["answers"][-1]
                resume_final = None
            else:
                record["attempts"] += 1
                attempt_started = time.monotonic()
                finished = await self._run_step(step, execution.accepted, feedback)
                worked += time.monotonic() - attempt_started
                record["seconds"] = round(worked, 1)
                if finished.status != "done" or finished.final is None:
                    if any(failure in finished.reason for failure in PROVIDER_FAILURES):
                        # Another attempt or a new plan would fail the same way: only this step fails
                        failed(f"the agent's model could not run: {finished.reason}")
                        return
                    feedback = _failure_feedback(finished)
                    last = record["rejections"][-1] if record["rejections"] else None
                    record["rejections"].append({"attempt": record["attempts"], "by": "code", "reason": feedback})
                    if last is not None and last["by"] == "code" and last["reason"] == feedback:
                        # The same problem twice in a row: the step as planned cannot pass (for example a
                        # deliverable declared as the wrong kind), so more attempts would only cost money
                        execution.failures.append(f"step '{step_id}' ({step['agent']}) was rejected twice for the same "
                                                  f"reason; fix the step in the plan. Reason: {feedback}")
                        failed(execution.failures[-1])
                        return
                    continue
                final = finished.final
                calls = [{"id": c.id, "name": c.name, "arguments": json.loads(c.arguments)}
                         for c in finished.pending_actions]
                record["result"] = final
                answer = {"result": final, "seconds": round(worked - worked_before, 1), "review": None}
                worked_before = worked
                record["answers"].append(answer)
                # Passed code: the agent's answer can be shown now, whole (drafts included), while the
                # Coordinator reviews it
                self._emit("step_done", {"id": step_id, "agent": step["agent"], "summary": final.get("summary"),
                                         "result": final, "seconds": answer["seconds"]})
            review_started = time.monotonic()
            # Kept until the review answers, so a failed review does not lose this answer
            self._awaiting_review[step_id] = {"final": final, "pending_actions": calls}
            review = await self._decide("review", self._review_input(step, final, execution.accepted))
            answer["review"] = {"decision": review["decision"], "note": review.get("note"),
                                "seconds": round(time.monotonic() - review_started, 1)}
            self._awaiting_review.pop(step_id, None)
            self._emit("step_reviewed", {"id": step_id, "agent": step["agent"], **answer["review"]})
            if review["decision"] == "accept":
                record["status"] = "accepted"
                execution.accepted[step_id] = final
                execution.pending_actions += [{**call, "step": step_id} for call in calls]
                self._emit("step_accepted", {"id": step_id, "agent": step["agent"],
                                             "summary": final.get("summary"), "seconds": record["seconds"]})
                return
            if review["decision"] == "replan":
                reason = f"step '{step_id}' ({step['agent']}): {review['feedback']}"
                if can_replan and not execution.stopped:
                    execution.replan = reason
                failed(reason)
                return
            if review["decision"] == "clarify":
                record["status"] = "clarify"
                if not execution.stopped:
                    execution.clarify = review
                return
            record["rejections"].append({"attempt": record["attempts"], "by": "coordinator", "reason": review["feedback"]})
            feedback = review["feedback"] + _dropped_actions([call["name"] for call in calls])
        execution.failures.append(f"step '{step_id}' ({step['agent']}) was rejected {record['attempts']} times; "
                                  f"last reason: {feedback}")
        failed(execution.failures[-1])

    async def _run_step(self, step: dict[str, Any], accepted: dict[str, dict[str, Any]], feedback: str | None) -> RunFinished:
        agent = self._agents[step["agent"]]
        inputs = {f"step:{dep}": _claim_values(accepted[dep]) for dep in step["depends_on"]}
        task = (
            f"<task>\nCoordinator step '{step['id']}': {step['task']}\n"
            f"<deliverables>\n{json.dumps(step['deliverables'], ensure_ascii=False)}\n</deliverables>\n"
        )
        if inputs:
            task += ("Claims of the steps this one depends on; cite one as a fact with "
                     "ref {call_id: \"step:<step id>\", path: \"<key>\"}.\n"
                     f"<step_inputs>\n{json.dumps(inputs, ensure_ascii=False)}\n</step_inputs>\n")
        if self._escalated:
            task += ("Claims checked before this plan, from the agent the request first went to; cite one as a "
                     "fact with ref {call_id: \"escalation\", path: \"<key>\"}.\n"
                     f"<escalation_claims>\n{json.dumps(self._escalated, ensure_ascii=False)}\n</escalation_claims>\n")
        task += f"</task>\n{self._today}"
        if self._room:
            task += f"\n{self._room}"
        if feedback:
            task += f"\n<feedback>\n{feedback}\n</feedback>"
        messages: list[Message] = [SystemMessage(content=agent.system_prompt), UserMessage(content=task)]
        sources = {**self._room_sources, **({"escalation": self._escalated} if self._escalated else {}), **inputs}
        finished = await self._run_agent(agent, messages, verifier(sources=sources,
                                                                   deliverables=step["deliverables"]))
        self._count(finished)
        return finished

    async def _decide(self, phase: str, blocks: str, allowed: Collection[str] | None = None) -> dict[str, Any]:
        self._emit("phase", {"phase": phase})
        messages: list[Message] = [
            SystemMessage(content=self._mandate.system_prompt),
            UserMessage(content=f"<task>{phase}</task>\n{self._today}\n{blocks}"),
        ]
        finished = await self._run_agent(self._mandate, messages, decision_verifier(
            phase, self._agents, self._unavailable, len(self._clarifications), self._kept, allowed,
            self._clarify_first))
        self._count(finished)
        if finished.status != "done" or finished.final is None:
            raise CoordinatorError(f"coordinator {phase} {finished.status}: {finished.reason}", self._checkpoint(phase))
        return finished.final

    def _plan_input(self, text: str, origin: str, escalation: dict[str, Any] | None,
                    plan: dict[str, Any] | None, failure: str | None, notes: dict[str, Any] | None = None) -> str:
        blocks = [
            _block("origin", origin),
            *([self._room] if self._room else []),
            _untrusted(text),
            _block("agent_catalog", _described(self._agents.values())),
            _block("unavailable_agents", _described(self._unavailable.values())),
            _block("max_parallel_steps", MAX_PARALLEL_STEPS),
            _block("clarify_rounds_used", len(self._clarifications)),
            *self._clarifications_block(),
        ]
        if escalation is not None:
            blocks.append(_block("escalation", escalation))
        blocks += [_block(name, value) for name, value in (notes or {}).items()]
        if failure is not None:
            blocks += [_block("plan", plan), _block("failure", failure)]
        if self._kept:
            blocks.append(_block("kept_results", {step_id: {"agent": k["agent"], "claims": _claim_values(k["result"])}
                                                  for step_id, k in self._kept.items()}))
        return "\n".join(blocks)

    def _review_input(self, step: dict[str, Any], result: dict[str, Any], accepted: dict[str, dict[str, Any]]) -> str:
        return "\n".join([
            _block("step", step),
            _block("step_result", result),
            _block("verification_report", "passed: every deliverable is present and every claim checks out"),
            # Only the claim values: enough to spot a contradiction, and this grows with every step
            _block("accepted_results", {step_id: _claim_values(result) for step_id, result in accepted.items()}),
            _block("clarify_rounds_used", len(self._clarifications)),
            *self._clarifications_block(),
        ])

    def _finalize_input(self, execution: _Execution) -> str:
        # The request and the agents out of reach let finalize name the parts left undone and why
        return "\n".join([
            *([self._room] if self._room else []),
            _untrusted(self._text),
            *self._clarifications_block(),
            _block("unavailable_agents", _described(self._unavailable.values())),
            _block("accepted_results", execution.accepted),
            _block("failed_steps", [{key: record[key] for key in ("id", "agent", "status", "reason")}
                                    for record in execution.records if record["status"] in ("failed", "skipped")]
                   + [{"id": record["id"], "agent": record["agent"], "status": "unfinished",
                       "reason": record["result"].get("summary")}
                      for record in execution.records if _unfinished(record)]),
            _block("pending_actions", execution.pending_actions),
        ])

    def _fallback_response(self, records: Sequence[dict[str, Any]]) -> str:
        """Written by code when the finalize call itself fails, so staff still see what was and was not done."""
        lines = ["Không tổng hợp được câu trả lời cuối. Kết quả từng bước:"]
        for step_id, kept in self._kept.items():
            lines.append(f"- {step_id} ({kept['agent']}): xong: {kept['result'].get('summary')}")
        for record in records:
            status = {"accepted": "xong", "failed": "lỗi", "skipped": "bỏ qua"}.get(record["status"], record["status"])
            detail = (record["result"] or {}).get("summary") if record["status"] == "accepted" else record["reason"]
            lines.append(f"- {record['id']} ({record['agent']}): {status}" + (f": {detail}" if detail else ""))
        return "\n".join(lines)

    def _clarifications_block(self) -> list[str]:
        """The user's earlier answers, as data like the request itself; none when nothing was asked."""
        if not self._clarifications:
            return []
        return [_untrusted(json.dumps(self._clarifications, ensure_ascii=False), "clarifications")]

    def _stopped(self, decision: dict[str, Any], plan: dict[str, Any] | None, records: list[dict[str, Any]]) -> Outcome:
        """An Outcome for a decision that ends the run before finalize."""
        kind = decision["decision"]
        if kind == "clarify":
            return self._outcome("clarify", decision["clarify_question"], plan, records)
        if kind == "request_agent":
            request = decision["agent_request"]
            return self._outcome("request_agent", f"Chưa có agent nào làm được phần việc này: {request['capability']}",
                                 plan, records, agent_request=request)
        return self._outcome(kind, decision["final_response"], plan, records)

    def _outcome(self, decision: str, output: str, plan: dict[str, Any] | None, records: list[dict[str, Any]],
                 agent_request: dict[str, Any] | None = None,
                 pending_actions: list[dict[str, Any]] | None = None) -> Outcome:
        return Outcome(decision, output, plan=plan, agent_request=agent_request, steps=records,
                       replans=self._replans, pending_actions=pending_actions or [],
                       usage=self._usage, model_steps=self._model_steps)

    def _count(self, finished: RunFinished) -> None:
        self._usage = Usage(self._usage.prompt_tokens + finished.usage.prompt_tokens,
                            self._usage.completion_tokens + finished.usage.completion_tokens)
        self._model_steps += finished.steps

    def _checkpoint(self, phase: str) -> dict[str, Any] | None:
        """Where the run stood when a Coordinator call failed, as plain JSON; None before any plan exists."""
        if self._plan is None:
            return None
        ex = self._execution
        return {
            "version": CHECKPOINT_VERSION,
            "plan": self._plan,
            "attempt": self._attempt,
            # Why the plan was redone; only a failed replan needs it again
            "failure": self._failure,
            "replans": list(self._replans),
            "kept": dict(self._kept),
            "records": copy.deepcopy(ex.records) if ex else [],
            "accepted": dict(ex.accepted) if ex else {},
            "pending_actions": list(ex.pending_actions) if ex else [],
            "awaiting_review": dict(self._awaiting_review),
            "failed_phase": phase,
        }

    async def resume(self, text: str, origin: str, checkpoint: dict[str, Any],
                     escalation: dict[str, Any] | None = None, clarifications: Sequence[dict[str, str]] = (),
                     notes: dict[str, Any] | None = None) -> Outcome:
        """Continue a run that a Coordinator call cut short, from its checkpoint: no new plan unless the
        failed call was the replan itself."""
        if checkpoint.get("version") != CHECKPOINT_VERSION:
            raise CoordinatorError(f"unsupported checkpoint version {checkpoint.get('version')!r}")
        self._text = text
        self._clarifications = list(clarifications)
        self._clarify_first = origin in CLARIFY_FIRST
        self._replans = list(checkpoint["replans"])
        self._kept = dict(checkpoint["kept"])
        plan = checkpoint["plan"]
        prior = {k: checkpoint[k] for k in ("accepted", "pending_actions", "awaiting_review", "records")}
        if checkpoint["failed_phase"] == "review":
            self._emit("plan", {"steps": [{"id": s["id"], "agent": s["agent"], "label": s["label"]}
                                          for s in plan["steps"]]})
            return await self._loop(text, origin, escalation, notes, checkpoint["attempt"], plan, prior,
                                    checkpoint["failure"], skip_plan=True)
        # The replan call failed: plan again from the dropped plan and its failure
        return await self._loop(text, origin, escalation, notes, checkpoint["attempt"] + 1, plan, None,
                                checkpoint["failure"])

    async def _loop(self, text: str, origin: str, escalation: dict[str, Any] | None, notes: dict[str, Any] | None,
                    start_attempt: int, plan: dict[str, Any] | None, prior: dict[str, Any] | None,
                    failure: str | None = None, skip_plan: bool = False) -> Outcome:
        # `plan` with `skip_plan` is a plan to run as it is (a resume); `prior` is what it already did
        execution: _Execution | None = None
        self._failure = failure
        # The escalated agent's claims passed code already: every step may cite them
        self._escalated = _claim_values(escalation or {})
        for attempt in range(start_attempt, MAX_REPLANS + 1):
            if not skip_plan:
                planned = await self._decide("plan", self._plan_input(text, origin, escalation, plan, failure, notes))
                if planned["decision"] != "plan":
                    return self._stopped(planned, plan, [])
                plan = planned["plan"]
                self._emit("plan", {"steps": [{"id": s["id"], "agent": s["agent"], "label": s["label"]} for s in plan["steps"]]})
            skip_plan = False
            self._plan = plan
            self._attempt = attempt
            execution = await self._execute(plan, can_replan=attempt < MAX_REPLANS, prior=prior)
            prior = None
            if execution.clarify is not None:
                return self._stopped(execution.clarify, plan, execution.records)
            if execution.failure is None or attempt == MAX_REPLANS:
                break
            failure = execution.failure
            self._failure = failure
            for record in execution.records:
                if record["status"] == "accepted":
                    self._kept[record["id"]] = {
                        "agent": record["agent"], "result": execution.accepted[record["id"]],
                        "pending_actions": [a for a in execution.pending_actions if a["step"] == record["id"]],
                    }
            # `steps` keeps what each step of the dropped plan did, so the whole run can be shown
            self._replans.append({"plan": plan, "failure": failure, "steps": execution.records})
        assert plan is not None and execution is not None
        allowed = finalize_decisions(execution.records, len(self._kept))
        try:
            finalized = await self._decide("finalize", self._finalize_input(execution), allowed)
        except CoordinatorError:
            # The work already done is not lost because the last model call failed
            return self._outcome(allowed[0], self._fallback_response(execution.records), plan, execution.records,
                                 pending_actions=execution.pending_actions)
        return self._outcome(finalized["decision"], finalized["final_response"], plan, execution.records,
                             pending_actions=execution.pending_actions)


def _failure_feedback(finished: RunFinished) -> str:
    """Why a worker run failed, with what code last found wrong in its `final_answer`.

    The next attempt starts from a fresh conversation, so without the problems themselves the agent
    would only learn that it failed, not what to fix.
    """
    feedback = f"the previous attempt ended '{finished.status}': {finished.reason}"
    final_calls = {call.id for message in finished.messages if isinstance(message, AssistantMessage)
                   for call in message.tool_calls if call.name == FINAL_ANSWER}
    for message in reversed(finished.messages):
        if isinstance(message, ToolResultMessage) and message.tool_call_id in final_calls and message.is_error:
            feedback = f"{feedback}\nWhat was wrong with its last {FINAL_ANSWER}:\n{message.content}"
            break
    return feedback + _dropped_actions([call.name for call in finished.pending_actions])


def _dropped_actions(names: Sequence[str]) -> str:
    """A note that a rejected attempt's queued high-risk calls are gone.

    Only an accepted attempt's calls reach staff, and the next attempt starts from a fresh
    conversation, so an agent that saw them queued would otherwise assume they still wait.
    """
    if not names:
        return ""
    names = ", ".join(dict.fromkeys(names))
    return (f"\nThe previous attempt queued {names} for staff approval, but that attempt was rejected, so "
            "the queued calls were dropped and will not reach staff. If the task still needs them, call them "
            "again in this attempt.")


def _described(agents: Iterable[Mandate]) -> list[dict[str, str]]:
    return [{"name": agent.name, "description": agent.description} for agent in agents]


def _untrusted(text: str, tag: str = "untrusted_input") -> str:
    """Staff-written text as data: it cannot close its own tag."""
    safe = text.replace(f"</{tag}>", f"&lt;/{tag}&gt;")
    return f"<{tag}>\n{safe}\n</{tag}>"


def _claim_values(result: dict[str, Any]) -> dict[str, Any]:
    return {claim["key"]: claim["value"] for claim in result.get("claims") or []}


def _block(tag: str, value: Any) -> str:
    body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"<{tag}>\n{body}\n</{tag}>"
