"""core.llm.parsing — JSON 解析 + Pydantic 校验."""
import pytest
from pydantic import BaseModel, ValidationError

from app.core.llm.parsing import extract_json, parse_json_as


class _Demo(BaseModel):
    name: str
    age: int


def test_extract_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fence():
    s = '```json\n{"a": 2}\n```'
    assert extract_json(s) == {"a": 2}


def test_extract_json_with_bare_fence():
    s = '```\n{"a": 3}\n```'
    assert extract_json(s) == {"a": 3}


def test_extract_json_with_prefix_suffix_noise():
    s = 'sure! here is: ```json\n{"a": 4}\n``` hope this helps.'
    assert extract_json(s) == {"a": 4}


def test_extract_invalid_json_raises():
    with pytest.raises(ValueError):
        extract_json("not json at all")


def test_parse_json_as_valid():
    obj = parse_json_as('{"name":"bob","age":30}', _Demo)
    assert obj.name == "bob"
    assert obj.age == 30


def test_parse_json_as_invalid_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_json_as('{"name":"bob","age":"not_a_number"}', _Demo)


def test_parse_json_as_strips_code_fence():
    s = '```json\n{"name":"x","age":1}\n```'
    obj = parse_json_as(s, _Demo)
    assert obj.name == "x"
