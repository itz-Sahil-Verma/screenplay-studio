import httpx
import openai
import pytest

from app.config import settings
from app.llm import LLMError, factory
from app.llm.azure import AzureOpenAIClient, base_url, is_reasoning
from app.llm.gemini import GeminiClient
from app.llm.groq_client import GroqClient
from app.models import SceneExtraction


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("app.llm.base.time.sleep", lambda s: None)


def _oa_err(cls, code, msg="boom"):
    req = httpx.Request("POST", "http://x")
    return cls(msg, response=httpx.Response(code, request=req), body=None)


class _Msg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


def _resp(text="{}"):
    return type("R", (), {"choices": [_Msg(text)], "usage": None})()


def _azure(behaviour, deployment="gpt-5"):
    c = AzureOpenAIClient.__new__(AzureOpenAIClient)
    c.deployment, c.last_usage = deployment, {}
    calls = []

    class _Completions:
        def create(self, **kw):
            calls.append(kw)
            return behaviour(kw)

    c._client = type("C", (), {"chat": type("Ch", (), {"completions": _Completions()})()})()
    return c, calls


# ---- Azure ---------------------------------------------------------------
@pytest.mark.parametrize("given", [
    "https://r.openai.azure.com", "https://r.openai.azure.com/",
    "https://r.openai.azure.com/openai", "https://r.openai.azure.com/openai/v1/",
])
def test_endpoint_normalised_to_v1_base_url(given):
    assert base_url(given) == "https://r.openai.azure.com/openai/v1/"


def test_reasoning_detection_is_exact_match_not_substring(monkeypatch):
    monkeypatch.setattr(settings, "azure_reasoning_deployments", "gpt-5, My-Reasoner")
    assert is_reasoning("gpt-5") and is_reasoning("GPT-5") and is_reasoning("my-reasoner")
    assert not is_reasoning("gpt-4.1-mini") and not is_reasoning("gpt-4.1")
    assert not is_reasoning("foo-gpt-5-bar") and not is_reasoning("foo3")  # no substring guessing


def test_reasoning_model_missing_from_setting_gives_actionable_error():
    def reject(kw):
        raise _oa_err(openai.BadRequestError, 400, "Unsupported parameter: 'temperature'")

    c, calls = _azure(reject, "chat-main")  # not in AZURE_REASONING_DEPLOYMENTS
    with pytest.raises(LLMError, match="AZURE_REASONING_DEPLOYMENTS"):
        c.complete_json("s", "p", SceneExtraction)
    assert len(calls) == 1


def test_non_reasoning_model_listed_by_mistake_gives_actionable_error():
    def reject(kw):
        raise _oa_err(openai.BadRequestError, 400, "Unrecognized request argument: reasoning_effort")

    c, _ = _azure(reject, "gpt-5")
    with pytest.raises(LLMError, match="Remove its name"):
        c.complete_json("s", "p", SceneExtraction)


def test_reasoning_model_gets_effort_and_no_temperature():
    c, calls = _azure(lambda kw: _resp(), "gpt-5")
    c.complete_json("s", "p", SceneExtraction)
    assert calls[0]["reasoning_effort"] == settings.azure_reasoning_effort
    assert "temperature" not in calls[0]


def test_standard_model_gets_temperature_and_no_effort():
    c, calls = _azure(lambda kw: _resp(), "gpt-4.1-mini")
    c.complete_json("s", "p", SceneExtraction)
    assert "temperature" in calls[0] and "reasoning_effort" not in calls[0]


def test_transient_error_retries_same_deployment_then_raises():
    def boom(kw):
        raise _oa_err(openai.RateLimitError, 429)

    c, calls = _azure(boom)
    with pytest.raises(openai.RateLimitError):
        c.complete_json("s", "p", SceneExtraction)
    assert [k["model"] for k in calls] == ["gpt-5", "gpt-5"]  # same model, no switching


def test_transient_error_then_success():
    state = {"n": 0}

    def flaky(kw):
        state["n"] += 1
        if state["n"] == 1:
            raise _oa_err(openai.InternalServerError, 500)
        return _resp('{"ok": 1}')

    c, _ = _azure(flaky)
    assert c.complete_json("s", "p", SceneExtraction) == '{"ok": 1}'


def test_missing_deployment_gives_actionable_error_without_retry():
    def nf(kw):
        raise _oa_err(openai.NotFoundError, 404)

    c, calls = _azure(nf, "typo-name")
    with pytest.raises(LLMError, match="AZURE_DEPLOYMENT"):
        c.complete_json("s", "p", SceneExtraction)
    assert len(calls) == 1


def test_bad_key_is_not_retried_or_masked():
    def bad(kw):
        raise _oa_err(openai.AuthenticationError, 401)

    c, calls = _azure(bad)
    with pytest.raises(openai.AuthenticationError):
        c.complete_json("s", "p", SceneExtraction)
    assert len(calls) == 1


# ---- Gemini (SDK stubbed) --------------------------------------------------
def _gemini(behaviour):
    c = GeminiClient.__new__(GeminiClient)
    c.model = "m1"
    calls = []

    class _Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            return behaviour(model)

    c._client = type("C", (), {"models": _Models()})()
    return c, calls


def _api_error(code):
    from google.genai import errors

    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_gemini_503_retries_same_model_then_raises():
    def boom(model):
        raise _api_error(503)

    c, calls = _gemini(boom)
    with pytest.raises(Exception, match="503"):
        c.complete_json("s", "p", SceneExtraction)
    assert calls == ["m1", "m1"]


def test_gemini_404_gives_actionable_error():
    def nf(model):
        raise _api_error(404)

    c, calls = _gemini(nf)
    with pytest.raises(LLMError, match="GEMINI_MODEL"):
        c.complete_json("s", "p", SceneExtraction)
    assert len(calls) == 1


# ---- Factory: one switch, no fallback ---------------------------------------
def _set(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setattr(settings, k, v)


def test_azure_selected_and_step_picks_deployment(monkeypatch):
    _set(monkeypatch, llm_provider="azure", azure_openai_endpoint="https://r.openai.azure.com",
         azure_openai_api_key="k", azure_deployment_extract="mini", azure_deployment_adapt="big")
    assert isinstance(factory.get_client("extract"), AzureOpenAIClient)
    assert factory.get_client("extract").deployment == "mini"
    assert factory.get_client("adapt").deployment == "big"


def test_switching_to_gemini_is_only_a_setting(monkeypatch):
    _set(monkeypatch, llm_provider="gemini", gemini_api_key="k",
         gemini_model_extract="ge", gemini_model_adapt="ga")
    c = factory.get_client("adapt")
    assert isinstance(c, GeminiClient) and c.model == "ga"


def test_switching_to_groq(monkeypatch):
    _set(monkeypatch, llm_provider="groq", groq_api_key="k", groq_model_extract="lm")
    assert isinstance(factory.get_client("extract"), GroqClient)


def test_no_cross_provider_fallback_even_if_other_keys_exist(monkeypatch):
    _set(monkeypatch, llm_provider="azure", azure_openai_endpoint="https://r.openai.azure.com",
         azure_openai_api_key="k", gemini_api_key="g", groq_api_key="q")
    c = factory.get_client("extract")
    assert c.name == "azure" and not hasattr(c, "clients")


def test_missing_settings_named_in_error(monkeypatch):
    _set(monkeypatch, llm_provider="azure", azure_openai_endpoint="", azure_openai_api_key="")
    with pytest.raises(LLMError) as e:
        factory.get_client("extract")
    assert "AZURE_OPENAI_ENDPOINT" in str(e.value) and "AZURE_OPENAI_API_KEY" in str(e.value)


def test_unknown_provider_and_step_rejected(monkeypatch):
    _set(monkeypatch, llm_provider="openia")
    with pytest.raises(LLMError, match="unknown LLM_PROVIDER"):
        factory.get_client("extract")
    with pytest.raises(ValueError):
        factory.get_client("nope")
