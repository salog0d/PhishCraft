"""Prometheus exporter for the local NVIDIA GPU (the Ollama accelerator).

Serves ``/metrics`` on ``:9400`` with per-GPU gauges derived from
``nvidia-smi`` (no pynvml dependency): VRAM used/total, utilization,
temperature, and power draw.

    venv/bin/python monitoring/gpu_exporter.py

Prometheus scrapes it through the compose network as
``host.docker.internal:9400`` (see ``monitoring/prometheus/prometheus.yml``).
Run it next to Ollama on the host — the containerized stack can't see the GPU
without the NVIDIA container toolkit.
"""

from __future__ import annotations

import os
import subprocess

from prometheus_client import (
    CollectorRegistry,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily

DEFAULT_PORT = 9400
QUERY = "index,name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
MIB = 1024 * 1024


class GpuCollector:
    def __init__(self) -> None:
        self.errors = 0

    def _smi_rows(self) -> list[list[str]]:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={QUERY}",
             "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return [line.split(", ") for line in out.splitlines() if line.strip()]

    def collect(self):
        try:
            rows = self._smi_rows()
        except Exception:  # no GPU / driver / timeout — report one error
            self.errors += 1
            yield self._errors_family(1.0)
            return
        yield self._errors_family(0.0)

        def f(value: str) -> float:
            try:
                return float(value)
            except ValueError:
                return 0.0

        up = GaugeMetricFamily(
            "phishcraft_gpu_up", "1 when the GPU is visible to nvidia-smi.",
            labels=["index", "name"],
        )
        mem_used = GaugeMetricFamily(
            "phishcraft_gpu_memory_used_bytes", "VRAM in use.",
            labels=["index", "name"],
        )
        mem_total = GaugeMetricFamily(
            "phishcraft_gpu_memory_total_bytes", "Total VRAM.",
            labels=["index", "name"],
        )
        util = GaugeMetricFamily(
            "phishcraft_gpu_utilization_ratio", "GPU utilization 0..1.",
            labels=["index", "name"],
        )
        temp = GaugeMetricFamily(
            "phishcraft_gpu_temperature_celsius", "GPU temperature.",
            labels=["index", "name"],
        )
        power = GaugeMetricFamily(
            "phishcraft_gpu_power_watts", "Power draw.",
            labels=["index", "name"],
        )
        for row in rows:
            index, name, used, total, util_pct, temp_c, watts = row
            labels = [index, name]
            up.add_metric(labels, 1.0)
            mem_used.add_metric(labels, f(used) * MIB)
            mem_total.add_metric(labels, f(total) * MIB)
            util.add_metric(labels, f(util_pct) / 100.0)
            temp.add_metric(labels, f(temp_c))
            power.add_metric(labels, f(watts))
        yield up
        yield mem_used
        yield mem_total
        yield util
        yield temp
        yield power

    def _errors_family(self, value: float) -> GaugeMetricFamily:
        family = GaugeMetricFamily(
            "phishcraft_gpu_exporter_errors_total",
            "nvidia-smi query failures (1 = broken scrape).",
        )
        family.add_metric([], value)
        return family


def main() -> None:
    port = int(os.getenv("GPU_EXPORTER_PORT", DEFAULT_PORT))
    # CollectorRegistry() auto-registers the platform/process/GC collectors.
    registry = CollectorRegistry()
    registry.register(GpuCollector())
    start_http_server(port, registry=registry)
    print(f"gpu exporter listening on :{port}", flush=True)
    import time

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
