"""Optional InfluxDB sink for slow-control readings.

The app must start and run in simulation mode without InfluxDB installed or
configured.  This wrapper is therefore a no-op unless ``influx.enabled`` is true
and ``influxdb-client`` can be imported.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class InfluxWriter:
    enabled: bool = False
    url: str = ""
    token: str = ""
    org: str = ""
    bucket: str = ""
    measurement: str = "slow_control"

    _client: Any = None
    _write_api: Any = None

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "InfluxWriter":
        cfg = cfg or {}
        writer = cls(
            enabled=bool(cfg.get("enabled", False)),
            url=str(cfg.get("url", "")),
            token=str(cfg.get("token", "")),
            org=str(cfg.get("org", "")),
            bucket=str(cfg.get("bucket", "")),
            measurement=str(cfg.get("measurement", "slow_control")),
        )
        if writer.enabled:
            writer._open()
        return writer

    def _open(self) -> None:
        try:
            from influxdb_client import InfluxDBClient
        except Exception as exc:
            logger.warning("InfluxDB enabled but influxdb-client unavailable: %s", exc)
            self.enabled = False
            return
        try:
            self._client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self._write_api = self._client.write_api()
        except Exception as exc:
            logger.warning("InfluxDB connection setup failed: %s", exc)
            self.enabled = False

    def write_readings(self, readings: dict[str, Any]) -> None:
        if not self.enabled or self._write_api is None:
            return
        fields: dict[str, float] = {}
        for name, reading in readings.items():
            value = getattr(reading, "value", reading)
            try:
                fields[str(name)] = float(value)
            except (TypeError, ValueError):
                continue
        if not fields:
            return
        point = {
            "measurement": self.measurement,
            "time": int(time.time_ns()),
            "fields": fields,
        }
        try:
            self._write_api.write(bucket=self.bucket, org=self.org, record=point)
        except Exception as exc:
            logger.warning("InfluxDB write failed: %s", exc)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.debug("InfluxDB close failed", exc_info=True)
        self._client = None
        self._write_api = None
