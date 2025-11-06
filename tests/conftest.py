"""Test fixtures for the spec-search pipeline."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Union

import sys
import types

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide stub modules so importing ``backend`` does not require optional extras.
if "python_multipart" not in sys.modules:
    stub = types.ModuleType("python_multipart")
    stub.multipart = types.ModuleType("python_multipart.multipart")
    sys.modules["python_multipart"] = stub
    sys.modules["python_multipart.multipart"] = stub.multipart

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")

    def _load_dotenv(*_args, **_kwargs):  # pragma: no cover - simple stub
        return None

    dotenv_stub.load_dotenv = _load_dotenv
    sys.modules["dotenv"] = dotenv_stub

if "pydantic" not in sys.modules:
    pydantic_stub = types.ModuleType("pydantic")

    class _FieldInfo:
        def __init__(self, default=None, default_factory=None, **_kwargs):
            self.default = default
            self.default_factory = default_factory

    def Field(*, default=None, default_factory=None, **kwargs):
        return _FieldInfo(default=default, default_factory=default_factory, **kwargs)

    def field_validator(field_name, mode="after"):
        def decorator(func):
            func.__field_validator__ = (field_name, mode)
            return func

        return decorator

    class _ModelMeta(type):
        def __new__(mcls, name, bases, namespace):
            annotations = dict(namespace.get("__annotations__", {}))
            fields = {}
            validators = {}
            for attr_name, attr in list(namespace.items()):
                marker = getattr(attr, "__field_validator__", None)
                if marker is not None:
                    field, mode = marker
                    validators.setdefault(field, []).append({"mode": mode, "func": attr})
                    namespace.pop(attr_name)
            for field_name, _annotation in annotations.items():
                default = namespace.get(field_name, _FieldInfo())
                if isinstance(default, _FieldInfo):
                    fields[field_name] = default
                    namespace.pop(field_name, None)
                else:
                    fields[field_name] = _FieldInfo(default=default)
                    namespace.pop(field_name, None)
            namespace["__fields__"] = fields
            namespace["__validators__"] = validators
            return super().__new__(mcls, name, bases, namespace)

    class BaseModel(metaclass=_ModelMeta):
        def __init__(self, **data):
            for name, field in self.__fields__.items():
                if name in data:
                    value = data[name]
                elif field.default_factory is not None:
                    value = field.default_factory()
                else:
                    value = field.default
                for validator in self.__validators__.get(name, []):
                    if validator["mode"] == "before":
                        func = validator["func"]
                        if isinstance(func, classmethod):
                            bound = func.__get__(None, self.__class__)
                        else:
                            bound = func
                        try:
                            value = bound(self.__class__, value)
                        except TypeError:
                            value = bound(value)
                setattr(self, name, value)
            for name, validators in self.__validators__.items():
                for validator in validators:
                    if validator["mode"] == "after":
                        current = getattr(self, name)
                        func = validator["func"]
                        if isinstance(func, classmethod):
                            bound = func.__get__(None, self.__class__)
                        else:
                            bound = func
                        try:
                            updated = bound(self.__class__, current)
                        except TypeError:
                            updated = bound(current)
                        setattr(self, name, updated)

        def model_dump(self):  # pragma: no cover - helper for compatibility
            return {name: getattr(self, name) for name in self.__fields__}

    class RootModel(BaseModel):
        __annotations__ = {"root": object}

        def __init__(self, root):
            super().__init__(root=root)

        @property
        def root(self):
            return getattr(self, "root")

    class BaseSettings(BaseModel):
        pass

    pydantic_stub.BaseModel = BaseModel
    pydantic_stub.RootModel = RootModel
    pydantic_stub.BaseSettings = BaseSettings
    pydantic_stub.Field = Field
    pydantic_stub.field_validator = field_validator
    sys.modules["pydantic"] = pydantic_stub


def pytest_pyfunc_call(pyfuncitem):
    if asyncio.iscoroutinefunction(pyfuncitem.obj):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(pyfuncitem.obj(**pyfuncitem.funcargs))
        finally:
            loop.close()
        return True
    return None

import pytest

from backend.llm_client import LLMClient, LLMRequest


class MockLLM(LLMClient):
    """Mock LLM client with queued responses."""

    def __init__(self) -> None:
        super().__init__(transport=self._dispatch)
        self._queue: List[Union[str, Exception]] = []
        self.requests: List[LLMRequest] = []

    def enqueue(self, response: Union[str, Exception]) -> None:
        self._queue.append(response)

    async def _dispatch(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if not self._queue:
            raise RuntimeError("MockLLM was called without a queued response")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def sample_text_simple() -> str:
    path = Path("tests/fixtures/sample_text_simple.txt")
    return path.read_text()


@pytest.fixture
def sample_text_normative() -> str:
    path = Path("tests/fixtures/sample_text_normative.txt")
    return path.read_text()
