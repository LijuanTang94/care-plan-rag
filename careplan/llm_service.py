"""LLM abstraction layer — same idea as the data-source Adapter, except
here we're "swapping models".

  ClaudeLLMService ─┐
  OpenAILLMService ─┼─→ BaseLLMService ─→ business logic (the worker only calls the
  MockLLMService   ─┘                      base class; it never knows the concrete impl)

The active provider is not hard-coded: it's read from the LLM_PROVIDER environment
variable (a feature flag). Switching models is a config change (.env / docker-compose) —
not a single line of code changes.
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from functools import lru_cache

logger = logging.getLogger("care-plan")

SYSTEM_PROMPT = """You are a clinical pharmacist assistant. Given a patient's
clinical information and a medication, generate a pharmacist-grade care plan.

The care plan MUST contain exactly these four sections, in this order:
1. Problem list / Drug therapy problems
2. Goals (SMART)
3. Pharmacist interventions / plan
4. Monitoring plan & lab schedule

Be concise and clinically appropriate. Output plain text only."""


def _build_user_content(*, patient_name, mrn, provider_name, npi, diagnosis,
                        medication, records, context: str = "") -> str:
    """Build the user prompt shared by every real provider (Claude / OpenAI / ...).
    Keeping it in one place means a new provider only has to wire up the API call."""
    ref_block = ""
    if context:   # RAG-retrieved material; placed first so the model grounds its output and cites sources
        ref_block = (
            "Use the following reference material to ground the care plan and cite "
            "sources in [brackets]. If a reference doesn't cover something, rely on "
            "standard clinical knowledge but stay conservative.\n\n"
            f"Reference material:\n{context}\n\n---\n"
        )
    return ref_block + f"""Patient: {patient_name}
MRN: {mrn}
Referring provider: {provider_name} (NPI {npi})
Primary diagnosis (ICD-10): {diagnosis}
Medication: {medication}

Patient records:
{records or "(none provided)"}

Generate the care plan for this medication."""


class BaseLLMService(ABC):
    """Unified interface for every LLM implementation. Business logic depends only on this."""

    @abstractmethod
    def generate(self, *, patient_name, mrn, provider_name, npi, diagnosis, medication, records, context: str = "") -> str:
        ...


class ClaudeLLMService(BaseLLMService):
    """The real Claude (Anthropic). Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def generate(self, *, patient_name, mrn, provider_name, npi, diagnosis, medication, records, context: str = "") -> str:
        logger.info("[Claude:%s] generating care plan: %s / %s", self.model, patient_name, medication)
        user_content = _build_user_content(
            patient_name=patient_name, mrn=mrn, provider_name=provider_name, npi=npi,
            diagnosis=diagnosis, medication=medication, records=records, context=context,
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return next(b.text for b in resp.content if b.type == "text")


class OpenAILLMService(BaseLLMService):
    """The real OpenAI (GPT). Reads OPENAI_API_KEY from the environment.

    Note the only difference from Claude is the API call shape (chat.completions +
    a system message in the messages list). Everything else — the shared prompt, the
    RAG context, the worker — is identical. That's the whole point of the abstraction:
    adding a provider is a subclass + one line in the factory registry below."""

    def __init__(self, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self.client = OpenAI()   # reads OPENAI_API_KEY
        self.model = model

    def generate(self, *, patient_name, mrn, provider_name, npi, diagnosis, medication, records, context: str = "") -> str:
        logger.info("[OpenAI:%s] generating care plan: %s / %s", self.model, patient_name, medication)
        user_content = _build_user_content(
            patient_name=patient_name, mrn=mrn, provider_name=provider_name, npi=npi,
            diagnosis=diagnosis, medication=medication, records=records, context=context,
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        return resp.choices[0].message.content


class MockLLMService(BaseLLMService):
    """Fake LLM: returns fixed text — no cost, no waiting (for testing). MOCK_DELAY can simulate latency."""

    def __init__(self):
        self.delay = int(os.environ.get("MOCK_DELAY", "0"))

    def generate(self, *, patient_name, mrn, provider_name, npi, diagnosis, medication, records, context: str = "") -> str:
        if self.delay:
            logger.info("[MOCK] pretending to generate, sleeping %d seconds...", self.delay)
            time.sleep(self.delay)
        logger.info("[MOCK] returning a fake care plan (no LLM call, no cost)")
        return f"""[MOCK CARE PLAN] {patient_name} (MRN {mrn}) — {medication}
Diagnosis: {diagnosis} · Provider: {provider_name} (NPI {npi})
RAG context used: {len(context)} chars

1. Problem list / Drug therapy problems
- (mocked) drug therapy problem for {medication}
2. Goals (SMART)
- (mocked) achieve clinical improvement safely
3. Pharmacist interventions / plan
- (mocked) dosing, monitoring, patient education
4. Monitoring plan & lab schedule
- (mocked) baseline labs, monitor during/after therapy

[This is a MOCKED response. Set LLM_PROVIDER=claude or openai to use a real API.]"""


# Factory registry — adding a provider is just one line here; business code and worker stay untouched.
# DeepSeek would be almost identical to OpenAI (OpenAI-compatible API): subclass OpenAILLMService
# with base_url="https://api.deepseek.com" and a deepseek-chat model.
_PROVIDERS = {
    "claude": ClaudeLLMService,
    "openai": OpenAILLMService,
    "mock": MockLLMService,
}


@lru_cache  # build each provider only once (don't recreate the client for every task)
def get_llm_service() -> BaseLLMService:
    provider = os.environ.get("LLM_PROVIDER", "claude")  # ← feature flag: read from env, not hard-coded
    cls = _PROVIDERS.get(provider)
    if cls is None:
        logger.warning("unknown LLM_PROVIDER=%s, falling back to claude", provider)
        cls = ClaudeLLMService
    logger.info("using LLM provider: %s", provider)
    return cls()
