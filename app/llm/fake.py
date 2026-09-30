"""Scripted LLM for tests: returns queued responses, records the prompts it saw."""
from pydantic import BaseModel


class FakeLLM:
    name = "fake"

    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, system: str, prompt: str, schema: type[BaseModel]) -> str:
        self.calls.append({"system": system, "prompt": prompt, "schema": schema.__name__})
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
