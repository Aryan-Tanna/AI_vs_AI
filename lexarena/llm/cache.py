"""Result cache + usage logging around any Backend.

A cache hit costs nothing against the subscription window, so a resumed or re-run job never pays
twice for an agent call it already completed.
"""
import hashlib
import json
from pathlib import Path

from lexarena.config import Settings
from lexarena.llm.agent import AgentResult, AgentSpec, Backend
from lexarena.session.ledger import UsageLedger


def cache_key(spec: AgentSpec, model: str, prompt: str) -> str:
    payload = {
        "role": spec.role, "model": model, "system": spec.system_prompt, "prompt": prompt,
        "tools": sorted(t.name for t in spec.tools), "salt": spec.cache_salt,
        "builtin": sorted(spec.builtin_tools), "rules": sorted(spec.allow_rules), "mcp": sorted(spec.external_mcp),
        "schema": spec.output_model.model_json_schema() if spec.output_model else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class CachedBackend:
    def __init__(self, inner: Backend, settings: Settings, ledger: UsageLedger):
        self.inner, self.settings, self.ledger = inner, settings, ledger
        self.dir: Path = settings.cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.job_key: str | None = None         # set by the runner for ledger attribution

    async def run(self, spec: AgentSpec, prompt: str) -> AgentResult:
        model = spec.model or self.settings.role(spec.role).model
        path = self.dir / f"{cache_key(spec, model, prompt)}.json"
        if path.exists():
            res = AgentResult(**json.loads(path.read_text(encoding="utf-8")))
            res.cached = True
        else:
            res = await self.inner.run(spec, prompt)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(res.to_dict(), ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        self.ledger.call(spec.role, res.model, res.num_turns, res.usage, res.cost_usd, res.cached, self.job_key)
        return res
