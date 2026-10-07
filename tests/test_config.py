"""Config is read from versioned YAML; nothing is defaulted in code (non-negotiable 4)."""

from __future__ import annotations

import copy
import types
import typing
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from lexarena.config import CRLF, LF, config_sha256, load_config
from lexarena.schemas.config import AppConfig
from tests.conftest import CONFIG_V1

RAW_V1: dict[str, Any] = yaml.safe_load(CONFIG_V1.read_text(encoding="utf-8"))


def _key_paths(d: dict[str, Any], prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    for key, value in d.items():
        path = (*prefix, key)
        yield path
        if isinstance(value, dict):
            yield from _key_paths(value, path)


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _model_classes(model: type[BaseModel], seen: set[type[BaseModel]]) -> Iterator[type[BaseModel]]:
    if model in seen:
        return
    seen.add(model)
    yield model
    for field in model.model_fields.values():
        stack: list[Any] = [field.annotation]
        while stack:
            ann = stack.pop()
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                yield from _model_classes(ann, seen)
            elif typing.get_origin(ann) is not None or isinstance(ann, types.UnionType):
                stack.extend(typing.get_args(ann))


def test_v1_loads() -> None:
    cfg = load_config(CONFIG_V1)
    assert cfg.version == "v1"
    assert cfg.session.alternating_turns == RAW_V1["session"]["alternating_turns"]


def test_no_config_field_has_a_code_default() -> None:
    offenders = [
        f"{model.__name__}.{name}"
        for model in _model_classes(AppConfig, set())
        for name, field in model.model_fields.items()
        if not field.is_required()
    ]
    assert offenders == []


@pytest.mark.parametrize("path", list(_key_paths(RAW_V1)), ids=lambda p: ".".join(p))
def test_every_key_is_required(tmp_path: Path, path: tuple[str, ...]) -> None:
    raw = copy.deepcopy(RAW_V1)
    node = raw
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["retrieval"]["surprise"] = 3
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_values_come_from_the_file(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["retrieval"]["top_k"] = RAW_V1["retrieval"]["top_k"] + 3
    raw["themis_local"]["retry_cap"] = RAW_V1["themis_local"]["retry_cap"] + 1
    cfg = load_config(_write(tmp_path, raw))
    assert cfg.retrieval.top_k == RAW_V1["retrieval"]["top_k"] + 3
    assert cfg.themis_local.retry_cap == RAW_V1["themis_local"]["retry_cap"] + 1


def test_config_hash_changes_with_content(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    first = config_sha256(_write(tmp_path, raw))
    raw["seed"] = raw["seed"] + 1
    assert config_sha256(_write(tmp_path, raw)) != first


def test_config_hash_ignores_line_endings(tmp_path: Path) -> None:
    unix = CONFIG_V1.read_bytes().replace(CRLF, LF)
    lf, crlf = tmp_path / "lf.yaml", tmp_path / "crlf.yaml"
    lf.write_bytes(unix)
    crlf.write_bytes(unix.replace(LF, CRLF))
    assert lf.read_bytes() != crlf.read_bytes()
    assert config_sha256(lf) == config_sha256(crlf)


def test_verifier_must_differ_in_family_from_lawyer(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"]["verifier"]["family"] = raw["models"]["lawyer"]["family"]
    with pytest.raises(ValidationError, match="family"):
        load_config(_write(tmp_path, raw))


def test_auditor_must_differ_in_family_from_lawyer(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"]["auditor"]["family"] = raw["models"]["lawyer"]["family"]
    with pytest.raises(ValidationError, match="family"):
        load_config(_write(tmp_path, raw))


def test_clerk_models_must_differ_in_family(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"]["clerk_secondary"]["family"] = raw["models"]["clerk_primary"]["family"]
    with pytest.raises(ValidationError, match="family"):
        load_config(_write(tmp_path, raw))


def test_drafter_models_must_differ_in_family(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"]["drafter_secondary"]["family"] = raw["models"]["drafter_primary"]["family"]
    with pytest.raises(ValidationError, match="drafter"):
        load_config(_write(tmp_path, raw))


def test_vocabulary_must_include_the_decision_date_and_in_force_parameter(tmp_path: Path) -> None:
    for key, required in (("case_date_labels", "DECISION"), ("overlay_parameters", "section_in_force")):
        raw = copy.deepcopy(RAW_V1)
        raw["vocabulary"][key] = [v for v in raw["vocabulary"][key] if v != required]
        with pytest.raises(ValidationError, match=required):
            load_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "role", ["verifier", "auditor", "clerk_primary", "clerk_secondary", "drafter_primary", "drafter_secondary"]
)
def test_verifiers_and_extractors_run_at_temperature_zero(tmp_path: Path, role: str) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"][role]["temperature"] = RAW_V1["models"]["lawyer"]["temperature"] + 0.1
    with pytest.raises(ValidationError, match="temperature"):
        load_config(_write(tmp_path, raw))


def test_role_must_reference_a_known_provider(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"]["judge"]["provider"] = "nonexistent"
    with pytest.raises(ValidationError, match="provider"):
        load_config(_write(tmp_path, raw))


def test_judging_weights_must_sum_to_one(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["judging"]["weights"]["accuracy"] = raw["judging"]["weights"]["accuracy"] + 0.5
    with pytest.raises(ValidationError, match="sum"):
        load_config(_write(tmp_path, raw))


def test_api_key_env_must_be_a_variable_name(tmp_path: Path) -> None:
    raw = copy.deepcopy(RAW_V1)
    raw["models"]["lawyer"]["api_key_env"] = "not a variable name!"
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_config_is_immutable() -> None:
    cfg: AppConfig = load_config(CONFIG_V1)
    with pytest.raises(ValidationError):
        cfg.seed = cfg.seed + 1  # type: ignore[misc]
