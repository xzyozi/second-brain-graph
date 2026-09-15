"""Unit tests for PythonLanguageVerifier in tools.lang."""


import pytest

from tools.lang import PythonLanguageVerifier, get_verifier


def test_get_verifier_factory():
    verifier = get_verifier("python")
    assert isinstance(verifier, PythonLanguageVerifier)

    verifier_py = get_verifier("py")
    assert isinstance(verifier_py, PythonLanguageVerifier)

    with pytest.raises(ValueError, match="Unsupported language verifier"):
        get_verifier("unknown_lang")


def test_python_verifier_valid_syntax(tmp_path):
    code = """import os
import json

class SampleApp:
    def run(self):
        try:
            print("Running app")
        except Exception as e:
            print(f"Error: {e}")
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(code, encoding="utf-8")

    verifier = PythonLanguageVerifier()
    res = verifier.verify_syntax(file_path)

    assert res.is_valid
    assert len(res.errors) == 0
    assert "os" in res.identifiers
    assert "SampleApp" in res.identifiers
    assert "run" in res.identifiers
    assert verifier.has_try_except_block(file_path)


def test_python_verifier_invalid_syntax(tmp_path):
    invalid_code = "def broken_func(: pass"
    file_path = tmp_path / "broken.py"
    file_path.write_text(invalid_code, encoding="utf-8")

    verifier = PythonLanguageVerifier()
    res = verifier.verify_syntax(file_path)

    assert not res.is_valid
    assert len(res.errors) > 0
    assert any("SyntaxError" in err for err in res.errors)


def test_python_verifier_required_identifiers(tmp_path):
    code = """import threading
from tkinter import messagebox

def process_order():
    threading.Thread(target=lambda: print("async")).start()
"""
    file_path = tmp_path / "order.py"
    file_path.write_text(code, encoding="utf-8")

    verifier = PythonLanguageVerifier()
    res = verifier.verify_identifiers(file_path, ["threading", "Thread", "messagebox", "process_order"])
    assert res.is_valid

    res_missing = verifier.verify_identifiers(file_path, ["threading", "NonExistentClass"])
    assert not res_missing.is_valid
    assert any("NonExistentClass" in err for err in res_missing.errors)


def test_python_verifier_has_try_except_block_negative(tmp_path):
    code = "def no_try():\n    print('hello')\n"
    file_path = tmp_path / "no_try.py"
    file_path.write_text(code, encoding="utf-8")

    verifier = PythonLanguageVerifier()
    assert not verifier.has_try_except_block(file_path)


def test_python_verifier_check_build(tmp_path):
    verifier = PythonLanguageVerifier()

    # Empty dir check
    empty_res = verifier.check_build(tmp_path)
    assert not empty_res.is_valid
    assert "No Python files found" in empty_res.errors[0]

    # Valid build check
    (tmp_path / "app.py").write_text("print('ok')", encoding="utf-8")
    valid_res = verifier.check_build(tmp_path)
    assert valid_res.is_valid

    # Invalid build check
    (tmp_path / "bad.py").write_text("def broken(:", encoding="utf-8")
    invalid_res = verifier.check_build(tmp_path)
    assert not invalid_res.is_valid
