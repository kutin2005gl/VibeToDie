"""Request and response bodies of the ai-service HTTP API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.coordinator import MAX_CLARIFY_ROUNDS


class Clarification(BaseModel):
    # A clarify_question the Coordinator asked, and the staff member's answer
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20000)


class RunRequest(BaseModel):
    task_id: int
    text: str = Field(min_length=1, max_length=20000)
    # Dev/test hook only (AI_ALLOW_PROVIDER_OVERRIDE=1): a provider profile from models.json, or "fake".
    # Otherwise ignored: every request runs on the provider an admin chose (services/provider.py).
    provider: str | None = Field(default=None, min_length=1)
    # Dev/test hook only (AI_ALLOW_AGENT_OVERRIDE=1): users never pick an agent, Jev routes every request
    agent: str | None = None
    # Earlier clarify rounds of this request, oldest first; the client keeps them between calls
    clarifications: list[Clarification] = Field(default_factory=list, max_length=MAX_CLARIFY_ROUNDS)


class RunResult(BaseModel):
    provider: str
    model: str
    # Readable rendering of `result`, for clients that only show text
    output: str
    input_tokens: int
    output_tokens: int
    agent: str
    steps: int
    # The validated final_answer: status, claims and the mandate's own fields
    result: dict[str, Any]
    # High-risk calls the model asked for; none ran, they wait for staff approval
    pending_actions: list[dict[str, Any]]
    # How Jev routed the request: branch, target and scores; null when the client named the agent
    route: dict[str, Any] | None


class RouteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class SessionOrigin(BaseModel):
    """Where a room was opened outside the web, so admins can find it and open it there.

    Told by the client and not checked against Slack: it only labels the room and links back to it."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["slack"]
    # Slack ids: a channel (a direct message is D...) and the ts of the thread's first message
    channel: str = Field(pattern=r"^[A-Z0-9]{1,32}$")
    thread_ts: str = Field(pattern=r"^[0-9]{1,16}\.[0-9]{1,8}$")
    # Only Slack's own https links, since the admin page renders it as a link
    permalink: str | None = Field(default=None, max_length=500,
                                  pattern=r"^https://([A-Za-z0-9-]+\.)+slack\.com/[^\s\"'<>]*$")


class SessionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    # Set by clients other than the web (the Slack bot); absent, the room's source is "web"
    origin: SessionOrigin | None = None
    # Dev/test hook only, like RunRequest.provider
    provider: str | None = Field(default=None, min_length=1)


class ProviderRequest(BaseModel):
    provider: str = Field(min_length=1)


class MessageRequest(BaseModel):
    # A new request in a room whose last turn is finished
    text: str = Field(min_length=1, max_length=20000)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)


class DecisionRequest(BaseModel):
    approve: bool

