"""Real API calls, one per distinct configured model. Run with: pytest --run-live -m live"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from lexarena.app import build_llm_client
from lexarena.config import load_config
from lexarena.prompts import PromptStore
from tests.conftest import CONFIG_V1, ENV_FILE, PROMPTS_ROOT

CFG = load_config(CONFIG_V1)
ROLES_BY_MODEL = {(m.provider, m.name, m.api_key_env): role for role, m in CFG.models.by_role().items()}


class SmokeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: int
    unit: str


@pytest.mark.live
@pytest.mark.parametrize("role", sorted(ROLES_BY_MODEL.values()))
def test_each_configured_model_returns_validated_json(role: str) -> None:
    client = build_llm_client(CFG, env_file=ENV_FILE, use_cache=False)
    prompt = PromptStore(PROMPTS_ROOT).render(CFG.prompts.smoke.id, CFG.prompts.smoke.version)
    result = client.complete_json(role=role, user=prompt, schema=SmokeAnswer, session_id=f"live-smoke-{role}")
    print(
        f"\n{role}: {CFG.models.by_role()[role].name} -> {result.value.model_dump_json()} "
        f"(attempts={result.attempts}, in={result.input_tokens}, out={result.output_tokens})"
    )
    assert result.value.answer > 0 and result.value.unit
