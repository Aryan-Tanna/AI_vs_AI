"""Source interfaces. A source declares whether it respects the case cutoff; in `eval` mode only cutoff-respecting
sources may be enabled, because evaluation must not see anything decided on or after the simulated decision."""
import datetime as dt
from dataclasses import dataclass, field
from typing import Literal, Protocol

Mode = Literal["eval", "live"]


@dataclass
class SourceInfo:
    name: str
    kind: Literal["authority", "law"]
    court: str | None = None             # SC / NCLAT / HC / ... for authority sources
    respects_cutoff: bool = True         # filters by decision date itself
    modes: set[str] = field(default_factory=lambda: {"eval", "live"})
    description: str = ""


class AuthoritySource(Protocol):
    info: SourceInfo

    def search(self, query: str, *, cutoff: dt.date, exclude: set[str], provisions: tuple[str, ...], k: int) -> list[dict]:
        """Ranked hits decided before `cutoff`, each a dict with at least title, decision_date, text."""

    def status(self, title: str, cutoff: dt.date):
        """An AuthorityStatus (found=False if unknown)."""


class LawSource(Protocol):
    info: SourceInfo

    def get(self, provision: str, as_of: dt.date):
        """A ProvisionAnswer (found=False if this source does not hold the provision)."""
