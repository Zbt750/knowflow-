from types import SimpleNamespace
from packaging.requirements import Requirement
import pytest

from scripts.export_runtime_constraints import resolve_observed, read_requirements, render_constraints


def test_transitive_extras_cycles_and_platform_markers():
    packages = {
        "root": ("1.0", ['binary>=2; extra == "binary"', 'optional; extra == "other"',
                         'unix; sys_platform == "linux"', 'shared[feature]']),
        "binary": ("2.1", ["root"]),
        "shared": ("3.0", ['extra-leaf; extra == "feature"']),
        "extra-leaf": ("4.0", []),
    }
    def provider(name):
        version, requires = packages[name]
        return SimpleNamespace(version=version, requires=requires)
    result = resolve_observed([Requirement("root"), Requirement("root[binary]")],
                              provider=provider, environment={"sys_platform": "win32"})
    assert result == {"binary": "2.1", "extra-leaf": "4.0", "root": "1.0", "shared": "3.0"}
    assert "unix" not in result and "optional" not in result


def test_version_conflict_is_not_hidden():
    with pytest.raises(ValueError, match="does not satisfy"):
        resolve_observed([Requirement("a<2")], provider=lambda _: SimpleNamespace(version="3", requires=[]))


def test_direct_url_cannot_be_exported_as_trusted_pin():
    with pytest.raises(ValueError, match="provenance"):
        resolve_observed([Requirement("a @ https://example.invalid/private.whl")])


def test_requirement_file_rejects_pip_includes_and_index_options(tmp_path):
    path = tmp_path / "req.txt"
    path.write_text("# comment\n-r private.txt\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PEP 508"):
        read_requirements([path])


def test_constraints_are_deterministic_and_disclaim_clean_install():
    result = render_constraints({"a": "1.0", "b": "2.0"})
    assert result.endswith("a==1.0\nb==2.0\n")
    assert "not a clean-environment certification" in result
    assert "Do not reuse as a Linux Docker lock" in result
