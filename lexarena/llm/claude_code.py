"""Agent backend that runs on the user's Claude subscription through the Claude Agent SDK.

The SDK drives the local Claude Code binary, which authenticates with the logged-in claude.ai account
(Pro/Max). Usage counts against that account's 5-hour and weekly windows. This is for the owner's own
research runs on their own machine; Anthropic does not allow offering claude.ai login inside a
product for other users (see CLAUDE.md §8.1b).

Isolation (CLAUDE.md §8.0): no built-in tools, no filesystem settings / CLAUDE.md / skills, no MCP
servers except ours, and an empty working directory. An agent can only reach data through the
tools in its AgentSpec.
"""
import os
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    query,
)

from lexarena.config import Settings
from lexarena.llm.agent import AgentError, AgentResult, AgentSpec, UsageLimitReached
from lexarena.session.ledger import UsageLedger

SERVER = "lex"
TRACE_RESULT_CHARS = 4000


def tool_id(name: str) -> str:
    return f"mcp__{SERVER}__{name}"


class ClaudeCodeBackend:
    def __init__(self, settings: Settings, ledger: UsageLedger):
        if os.environ.get("ANTHROPIC_API_KEY") and not settings.allow_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set: Claude Code would bill the API instead of the subscription. "
                "Unset it, or set LEX_ALLOW_API_KEY=true if API billing is intended.")
        self.settings = settings
        self.ledger = ledger
        settings.sandbox_dir.mkdir(parents=True, exist_ok=True)

    def build_options(self, spec: AgentSpec) -> ClaudeAgentOptions:
        role = self.settings.role(spec.role)
        mcp = {SERVER: create_sdk_mcp_server(SERVER, tools=spec.tools)} if spec.tools else {}
        return ClaudeAgentOptions(
            tools=[],                                   # no Read/Bash/Grep/WebFetch...
            allowed_tools=[tool_id(t.name) for t in spec.tools],
            mcp_servers=mcp,
            strict_mcp_config=True,
            setting_sources=[],                         # no CLAUDE.md, settings, memory
            skills=[],
            system_prompt=spec.system_prompt,
            model=spec.model or role.model,
            max_turns=spec.max_turns or role.max_turns,
            permission_mode="dontAsk",                  # anything not allow-listed is denied
            cwd=str(self.settings.sandbox_dir),
            output_format=({"type": "json_schema", "schema": spec.output_model.model_json_schema()}
                           if spec.output_model else None),
        )

    async def run(self, spec: AgentSpec, prompt: str) -> AgentResult:
        options = self.build_options(spec)
        texts: list[str] = []
        trace: list[dict[str, Any]] = []
        result: ResultMessage | None = None
        model_seen: str | None = None

        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, RateLimitEvent):
                info = msg.rate_limit_info
                self.ledger.rate_limit(info.status, info.resets_at, info.rate_limit_type, info.utilization)
                if info.status == "rejected":
                    raise UsageLimitReached(info.resets_at, info.rate_limit_type)
            elif isinstance(msg, AssistantMessage):
                model_seen = msg.model or model_seen
                if msg.error == "rate_limit":
                    raise UsageLimitReached(self.ledger.blocked_until(), None, "assistant error rate_limit")
                if msg.error in ("authentication_failed", "billing_error"):
                    raise AgentError(f"{msg.error}: run `claude` once and log in with the subscription account")
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        trace.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        content = block.content if isinstance(block.content, str) else str(block.content)
                        trace.append({"type": "tool_result", "id": block.tool_use_id,
                                      "is_error": bool(block.is_error), "content": content[:TRACE_RESULT_CHARS]})
            elif isinstance(msg, ResultMessage):
                result = msg

        if result is None:
            raise AgentError("no result message from Claude Code")
        if result.is_error:
            if result.api_error_status == 429:
                raise UsageLimitReached(self.ledger.blocked_until(), None, "HTTP 429")
            raise AgentError(f"{result.subtype}: {result.errors or result.result}")

        output = None
        if spec.output_model is not None:
            if result.structured_output is None:
                raise AgentError(f"{spec.role}: no structured output (subtype={result.subtype})")
            output = spec.output_model.model_validate(result.structured_output).model_dump(mode="json")

        return AgentResult(
            output=output,
            text=result.result or "\n".join(texts),
            num_turns=result.num_turns,
            usage=result.usage or {},
            cost_usd=result.total_cost_usd,
            trace=trace,
            session_id=result.session_id,
            model=model_seen or options.model,
        )
