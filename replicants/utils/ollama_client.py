"""Backward-compatible imports; prefer ``replicants.inference`` for new code."""

from __future__ import annotations

from replicants.inference.openai_transport import OpenAICompatibleTransport
from replicants.inference.types import ChatCompletionResult, ToolCallSpec

# Historical name — same implementation as the OpenAI-compatible transport.
OllamaClient = OpenAICompatibleTransport

__all__ = ["ChatCompletionResult", "OllamaClient", "ToolCallSpec", "OpenAICompatibleTransport"]
