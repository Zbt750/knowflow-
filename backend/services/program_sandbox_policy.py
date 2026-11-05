"""Fail-closed execution policy prototype; deliberately does not execute code."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SandboxPolicy:
    enabled: bool = False
    image_digest: str | None = None
    timeout_seconds: int = 5
    memory_mb: int = 128
    output_bytes: int = 65536

    def validate(self):
        if not self.enabled:
            raise ValueError("program_execution_disabled")
        if not self.image_digest or not re.fullmatch(r"[a-z0-9][a-z0-9./_-]*@sha256:[a-f0-9]{64}", self.image_digest):
            raise ValueError("sandbox_requires_reviewed_pinned_image")
        if not (1 <= self.timeout_seconds <= 10 and 32 <= self.memory_mb <= 256 and 1024 <= self.output_bytes <= 65536):
            raise ValueError("sandbox_limits_invalid")

    def container_create_args(self, *, name: str):
        self.validate()
        if not re.fullmatch(r"kaoyan-test-[a-f0-9]{32}", name):
            raise ValueError("invalid_container_name")
        # No host volume, Docker socket, network, privileged flag, or shell.
        # A future supervisor must enforce timeout, output cap and forced cleanup.
        return ["docker", "create", "--name", name, "--network", "none", "--read-only",
                "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "32", "--cpus", "0.5", "--memory", f"{self.memory_mb}m",
                "--memory-swap", f"{self.memory_mb}m", "--log-driver", "none",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--interactive", self.image_digest]
