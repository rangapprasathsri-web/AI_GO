"""
Measurement Level Detection & Hardware Inspection Module.

Detects runtime environment and assigns appropriate measurement classification:
- Level 0: Simulated / Mock Provider (No GPU counters, no external keys, relative proxy units).
- Level 1: Real Hosted Provider (External API keys present, measured latency, provider usage).
- Level 2: Local Hardware Counters (NVML/RAPL hardware counters, local diffusion weights).

Strict Rule: Never claim Level 2 or physical energy without readable hardware counters.
"""

from dataclasses import dataclass
import os
import platform
from typing import Any, Optional


@dataclass
class MeasurementEnvironment:
    level: int  # 0, 1, or 2
    level_name: str  # "Level 0: Simulated Proxy", "Level 1: Real Hosted Provider", "Level 2: Measured Hardware"
    provider_type: str  # "mock", "hosted", "local_hardware"
    has_gpu: bool
    gpu_name: Optional[str]
    has_rapl_access: bool
    has_hosted_credentials: bool
    latency_measured: bool
    energy_measured: bool
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "level_name": self.level_name,
            "provider_type": self.provider_type,
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name,
            "has_rapl_access": self.has_rapl_access,
            "has_hosted_credentials": self.has_hosted_credentials,
            "latency_measured": self.latency_measured,
            "energy_measured": self.energy_measured,
            "details": self.details,
        }


def detect_measurement_level() -> MeasurementEnvironment:
    """Inspect system hardware and environment variables to determine active measurement level."""
    # 1. Check for readable Intel RAPL counter
    rapl_readable = False
    rapl_path = "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
    if os.path.exists(rapl_path):
        try:
            with open(rapl_path, "r") as f:
                f.read(10)
                rapl_readable = True
        except (PermissionError, OSError):
            rapl_readable = False

    # 2. Check for GPU via torch or nvml
    has_gpu = False
    gpu_name = None
    try:
        import torch
        if torch.cuda.is_available():
            has_gpu = True
            gpu_name = torch.cuda.get_device_name(0)
    except ImportError:
        pass

    # 3. Check for hosted provider API credentials
    has_hosted = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("STABILITY_API_KEY"))

    # Determine level
    cpu_model = platform.processor() or "x86_64 CPU"
    
    if has_gpu and rapl_readable:
        return MeasurementEnvironment(
            level=2,
            level_name="Level 2: Measured Hardware Counters",
            provider_type="local_hardware",
            has_gpu=True,
            gpu_name=gpu_name,
            has_rapl_access=True,
            has_hosted_credentials=has_hosted,
            latency_measured=True,
            energy_measured=True,
            details=f"Local execution with hardware counter power readings ({gpu_name}).",
        )
    elif has_hosted:
        return MeasurementEnvironment(
            level=1,
            level_name="Level 1: Real Hosted Provider",
            provider_type="hosted",
            has_gpu=has_gpu,
            gpu_name=gpu_name,
            has_rapl_access=False,
            has_hosted_credentials=True,
            latency_measured=True,
            energy_measured=False,
            details="Upstream hosted provider with measured wall-clock latency; energy is not observable.",
        )
    else:
        return MeasurementEnvironment(
            level=0,
            level_name="Level 0: Simulated Proxy (Demo Mode)",
            provider_type="mock",
            has_gpu=False,
            gpu_name=None,
            has_rapl_access=False,
            has_hosted_credentials=False,
            latency_measured=False,
            energy_measured=False,
            details="Mock provider; compute units are a relative mathematical proxy; latency & energy not measured.",
        )
