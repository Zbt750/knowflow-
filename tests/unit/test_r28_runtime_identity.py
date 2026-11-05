"""No database connections: strict Windows runtime-directory decoding contracts."""
import ctypes
from types import SimpleNamespace
import pytest
from scripts import r25_full_pytest as runner


def test_utf8_directory_bytes_are_decoded_without_replacement():
    path = str(runner.PROJECT) + "/tmp/pg63047"
    assert runner._decode_server_directory(path.encode("utf8")) == path


def test_windows_ansi_directory_is_decoded_using_actual_os_code_page_contract(monkeypatch):
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GetACP=lambda:936)), raising=False)
    path = str(runner.PROJECT) + "/tmp/pg63047"
    assert runner._decode_server_directory(path.encode("cp936")) == path


def test_undecodable_directory_is_rejected_not_silently_repaired(monkeypatch):
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GetACP=lambda:936)), raising=False)
    with pytest.raises(UnicodeDecodeError):
        runner._decode_server_directory(b"D:/\x81")
