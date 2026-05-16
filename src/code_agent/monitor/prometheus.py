from __future__ import annotations

import time
from typing import Any

import prometheus_client
from prometheus_client import Counter, Gauge, REGISTRY

from code_agent.monitor.collector import MetricsCollector


class PrometheusExporter:
    """Bridge between MetricsCollector and prometheus_client library.

    Syncs in-memory SQLite metrics to Prometheus metrics for proper exposition.
    Metrics are refreshed on each call to ``collect()`` or ``generate()``.
    """

    def __init__(self, collector: MetricsCollector):
        self.collector = collector
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}
        self._last_refresh = 0.0
        self._refresh_interval = 5.0

    def _refresh(self) -> None:
        now = time.time()
        if now - self._last_refresh < self._refresh_interval:
            return
        self._last_refresh = now
        for m in self.collector.list_metrics():
            name = m["name"].replace("-", "_").replace(" ", "_")
            mtype = m.get("type", "counter")
            if name not in self._metrics:
                if mtype == "counter":
                    self._metrics[name] = Counter(name, name, registry=REGISTRY)
                elif mtype == "gauge":
                    self._metrics[name] = Gauge(name, name, registry=REGISTRY)
                else:
                    self._metrics[name] = Gauge(name, name, registry=REGISTRY)
            metric = self._metrics[name]
            last = float(m.get("last", 0))
            if isinstance(metric, Counter):
                metric._value.set(last)
            else:
                metric.set(last)

    def collect(self) -> list[Any]:
        self._refresh()
        return list(REGISTRY.collect())

    def generate(self) -> bytes:
        self._refresh()
        return prometheus_client.generate_latest(REGISTRY)

    def content_type(self) -> str:
        return prometheus_client.CONTENT_TYPE_LATEST
