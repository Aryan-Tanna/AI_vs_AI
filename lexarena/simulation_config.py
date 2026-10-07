"""Legacy simulation run configuration for the agent orchestrator and Streamlit UI."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class RoleModel(BaseModel):
    model: str  # Claude Code model alias or full ID ("haiku", "sonnet", "opus", ...)
    max_turns: int = 12
    thinking: bool = True


def _default_roles() -> dict[str, RoleModel]:
    return {
        "smoke": RoleModel(model="haiku", max_turns=4),
        "baseline": RoleModel(model="sonnet", max_turns=4),
        "advocate": RoleModel(model="sonnet", max_turns=12),
        "judge": RoleModel(model="opus", max_turns=12),
        "extractor": RoleModel(model="haiku", max_turns=6, thinking=False),
        "verifier": RoleModel(model="haiku", max_turns=4, thinking=False),
        "auditor": RoleModel(model="sonnet", max_turns=4, thinking=False),
        "order_writer": RoleModel(model="haiku", max_turns=4, thinking=False),
        "reflector": RoleModel(model="sonnet", max_turns=10),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEX_", env_file=".env", extra="ignore")

    data_dir: Path = ROOT / "data"
    mode: Literal["eval", "live"] = "eval"
    sources_file: Path = ROOT / "config" / "sources.yaml"
    public_db_dir: Path = ROOT / "public_db"
    runs_dir: Path = ROOT / "runs"
    roles: dict[str, RoleModel] = Field(default_factory=_default_roles)

    stop_at_utilization: float = 0.85
    max_session_hours: float = 4.75
    reset_buffer_s: int = 120
    unknown_reset_wait_s: int = 1800
    max_job_attempts: int = 3

    allow_api_key: bool = False

    @property
    def reference_path(self) -> Path:
        return self.data_dir / "canonical" / "reference_cases.jsonl"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def jobs_db(self) -> Path:
        return self.state_dir / "jobs.sqlite3"

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "usage_ledger.jsonl"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache" / "agent"

    @property
    def sandbox_dir(self) -> Path:
        return self.data_dir / "sandbox"

    def role(self, name: str) -> RoleModel:
        return self.roles[name]
