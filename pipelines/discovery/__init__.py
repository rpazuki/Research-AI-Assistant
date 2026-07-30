"""Seed resolution and candidate discovery for the datasheet feature.

Pure modules: HTTP against public APIs, no database, no LLM. Everything here is
callable from a script, the backend (via ``asyncio.to_thread``) or a test with an
injected transport.
"""
