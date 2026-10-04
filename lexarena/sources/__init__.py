"""Pluggable data sources (precedent DBs, law DBs, seeds, web, MCP servers), configured in config/sources.yaml.

Nothing downstream knows which databases exist: agents' tools and THEMIS ask the SourceRegistry, which fans out
to every source enabled for the current mode. Add a database by adding a config entry (or, for a new storage
kind, registering a source type with `register_source_type`).
"""
from lexarena.sources.registry import SourceRegistry, register_source_type

__all__ = ["SourceRegistry", "register_source_type"]
