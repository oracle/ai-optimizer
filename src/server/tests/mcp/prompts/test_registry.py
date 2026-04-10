"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.mcp.prompts.registry.
"""
# spell-checker: disable

from __future__ import annotations

from types import SimpleNamespace

from server.app.core.mcp import mcp
from server.app.core.settings import settings
from server.app.mcp.prompts import registry
from server.app.mcp.prompts.defaults import FACTORY_PROMPTS
from server.app.mcp.prompts.schemas import PromptConfig


def test_find_prompt_case_insensitive(prompt_config_factory):
    """find_prompt should match names ignoring case."""
    prompt_config_factory("Example", "text", title="Example")
    prompt_config_factory("another", "other", title="another")

    result = registry.find_prompt("EXAMPLE")
    assert isinstance(result, PromptConfig)
    assert result.name == "Example"

    assert registry.find_prompt("missing") is None


def test_prompt_to_response_fields(prompt_config_factory):
    """prompt_to_response includes only expected fields."""
    prompt = prompt_config_factory("Example", "text", title="Example", tags=["test"])
    prompt.description = "desc"

    response = registry.prompt_to_response(prompt)

    assert response == {
        "name": "Example",
        "description": "desc",
        "text": "text",
    }


def test_load_factory_prompts_populates(caplog):
    """load_factory_prompts replaces settings.prompt_configs."""
    caplog.set_level("INFO")
    registry.load_factory_prompts()

    assert len(settings.prompt_configs) == len(FACTORY_PROMPTS)
    assert caplog.records[-1].msg.startswith("Loaded")


def test_reconcile_prompt_customizations(caplog):
    """reconcile_prompt_customizations overlays matching prompts."""
    caplog.set_level("INFO")
    registry.load_factory_prompts()
    original_text = registry.find_prompt("optimizer_basic-default").text  # type: ignore[union-attr]
    custom = PromptConfig(
        name="optimizer_basic-default",
        title="Custom",
        description="",
        tags=[],
        text="Custom text",
    )
    ignored = PromptConfig(
        name="nonexistent",
        title="Ignored",
        description="",
        tags=[],
        text="Ignored text",
    )

    registry.reconcile_prompt_customizations([custom, ignored])

    updated = registry.find_prompt("optimizer_basic-default")
    assert updated is not None
    assert updated.text == "Custom text"
    assert caplog.records[-1].msg.startswith("Reconciled")

    # ensure other prompts unchanged
    other = registry.find_prompt("optimizer_tools-default")
    assert other is not None
    assert other.text != "Custom text"
    # original text changed, so ensure we didn't mutate baseline reference
    assert original_text != updated.text


def test_get_factory_text_hit_and_miss():
    """get_factory_text returns prompt text only for factory names."""
    assert registry.get_factory_text("optimizer_basic-default") is not None
    assert registry.get_factory_text("not-present") is None


def test_register_mcp_prompt_replaces(monkeypatch, prompt_config_factory):
    """register_mcp_prompt removes previous prompt and adds new one."""
    prompt = prompt_config_factory("prompt-one", "hello world", title="Prompt One")

    removed: list[str] = []

    def _record_remove(name: str) -> None:
        removed.append(name)

    monkeypatch.setattr(mcp.local_provider, "remove_prompt", _record_remove)

    captured = {}

    def fake_from_function(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name=kwargs["name"])

    monkeypatch.setattr(registry, "Prompt", SimpleNamespace(from_function=fake_from_function))
    added: list[object] = []

    def _capture_prompt(prompt_obj):
        added.append(prompt_obj)

    monkeypatch.setattr(mcp, "add_prompt", _capture_prompt)

    registry.register_mcp_prompt(prompt)

    assert removed == ["prompt-one"]
    assert added == [SimpleNamespace(name="prompt-one")]
    assert captured["name"] == "prompt-one"
    assert captured["title"] == "Prompt One"
    assert captured["description"] == ""
    assert captured["tags"] is None
    assert callable(captured["fn"])
    assert captured["fn"]() == "hello world"


def test_register_mcp_prompt_handles_missing(monkeypatch, prompt_config_factory):
    """register_mcp_prompt tolerates missing prior registration."""
    prompt = prompt_config_factory("prompt-two", "content", title="Prompt Two")

    def fake_remove(name):
        raise KeyError

    monkeypatch.setattr(mcp.local_provider, "remove_prompt", fake_remove)

    created = SimpleNamespace(instance=None)

    def fake_from_function(**kwargs):
        created.instance = kwargs
        return SimpleNamespace(name=kwargs["name"])

    monkeypatch.setattr(registry, "Prompt", SimpleNamespace(from_function=fake_from_function))
    added: list[object] = []

    def _capture_prompt(prompt_obj):
        added.append(prompt_obj)

    monkeypatch.setattr(mcp, "add_prompt", _capture_prompt)

    registry.register_mcp_prompt(prompt)

    assert added == [SimpleNamespace(name="prompt-two")]
    assert created.instance["name"] == "prompt-two"


def test_register_mcp_prompts_calls_individual(monkeypatch):
    """register_mcp_prompts delegates to register_mcp_prompt per entry."""
    prompts = [
        PromptConfig(name="a", title="A", description="", tags=[], text="A"),
        PromptConfig(name="b", title="B", description="", tags=[], text="B"),
    ]
    settings.prompt_configs = prompts

    called: list[str] = []

    def fake_register(pc: PromptConfig) -> None:
        called.append(pc.name)

    monkeypatch.setattr(registry, "register_mcp_prompt", fake_register)

    registry.register_mcp_prompts()

    assert called == ["a", "b"]
