"""Export dependency closure from the installed environment, without installing.

Observed constraints are not a wheel/hash lock or clean-environment acceptance.
Only declared project requirements and their active dependencies are included.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import platform
import sys

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def read_requirements(paths):
    result = []
    for path in paths:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-"):
                raise ValueError("Only PEP 508 requirements are accepted")
            result.append(Requirement(line))
    return result


def resolve_observed(requirements, *, provider=distribution, environment=None):
    environment = environment or default_environment()
    queue = list(requirements)
    extras, versions, visited = {}, {}, {}
    while queue:
        requirement = queue.pop(0)
        if requirement.url:
            raise ValueError("Direct URL dependencies need separate provenance review")
        if requirement.marker and not requirement.marker.evaluate({**environment, "extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        package = provider(name)
        version = str(Version(package.version))
        if requirement.specifier and not requirement.specifier.contains(version, prereleases=True):
            raise ValueError(f"Installed version does not satisfy requirement: {name}")
        versions[name] = version
        extras.setdefault(name, set()).update(requirement.extras)
        active = frozenset(extras[name])
        if visited.get(name) == active:
            continue
        visited[name] = active
        for raw in package.requires or []:
            dependency = Requirement(raw)
            if dependency.marker and not any(dependency.marker.evaluate({**environment, "extra": extra})
                                             for extra in {"", *active}):
                continue
            # The marker has already been evaluated in the parent's extras.
            dependency.marker = None
            queue.append(dependency)
    return dict(sorted(versions.items()))


def render_constraints(versions):
    return ("# Observed installed dependency closure; not a clean-environment certification.\n"
            "# Windows / Python 3.12 profile. Do not reuse as a Linux Docker lock.\n"
            "# Regenerate with scripts/export_runtime_constraints.py in the validated environment.\n"
            + "".join(f"{name}=={version}\n" for name, version in versions.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32":
        parser.error("This profile is explicitly Windows Python 3.12")
    output, report = args.output.resolve(), args.report.resolve()
    allowed = (ROOT / "constraints").resolve()
    reports = (ROOT / "eval/reports").resolve()
    if (output.parent != allowed or not report.is_relative_to(reports)
            or output.exists() or report.exists()):
        parser.error("Use new constraints and local report paths; existing evidence is not overwritten")
    paths = [ROOT / "requirements.txt", ROOT / "requirements-embed.txt"]
    versions = resolve_observed(read_requirements(paths))
    content = render_constraints(versions)
    record = {"version": "observed-runtime-constraints-v1", "created_at": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "platform": sys.platform,
              "requirements_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              "constraints_sha256": hashlib.sha256(content.encode()).hexdigest(), "packages": versions,
              "clean_install_verified": False, "artifact_hashes_locked": False,
              "limitations": ["local_installed_versions_only", "no_cross_platform_resolution",
                              "no_wheel_availability_or_offline_install_proof", "ragas_profile_excluded"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    with report.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"packages": len(versions), "clean_install_verified": False,
                      "artifact_hashes_locked": False, "constraints_sha256": record["constraints_sha256"]}))


if __name__ == "__main__":
    main()
