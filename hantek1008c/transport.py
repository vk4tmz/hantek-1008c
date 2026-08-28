from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

import usb.core
import usb.util

VID=0x0783
PID=0x5725
INTERFACE=0
EP_IN=0x81
EP_OUT=0x02
MAX_PACKET=64

class HantekUSBError(RuntimeError):
    pass

def hex_bytes(data: bytes | bytearray | Iterable[int]) -> str:
    return " ".join(f"{int(b):02X}" for b in data)

@dataclass(frozen=True)
class Transaction:
    timestamp: str
    tx: bytes
    rx: bytes | None
    timed_out: bool

    def as_dict(self):
        return {
            "timestamp": self.timestamp,
            "tx_hex": self.tx.hex().upper(),
            "rx_hex": None if self.rx is None else self.rx.hex().upper(),
            "timed_out": self.timed_out,
        }

class Hantek1008C:
    def __init__(self, *, logger_path=None):
        self.logger_path=Path(logger_path) if logger_path else None
        self.dev=None
        self._claimed=False

    def open(self):
        dev=usb.core.find(idVendor=VID,idProduct=PID)
        if dev is None:
            raise HantekUSBError(f"Hantek 1008C not found ({VID:04x}:{PID:04x})")
        try:
            cfg=dev.get_active_configuration()
        except usb.core.USBError as exc:
            raise HantekUSBError(f"Unable to access USB configuration: {exc}") from exc
        if cfg.bConfigurationValue != 1:
            raise HantekUSBError(f"Unexpected active configuration {cfg.bConfigurationValue}")
        try:
            try:
                active=dev.is_kernel_driver_active(INTERFACE)
            except (NotImplementedError, usb.core.USBError):
                active=False
            if active:
                raise HantekUSBError("Kernel driver is active on interface 0; refusing to detach automatically")
            usb.util.claim_interface(dev,INTERFACE)
        except usb.core.USBError as exc:
            raise HantekUSBError(f"Unable to claim interface 0: {exc}") from exc
        self.dev=dev
        self._claimed=True
        return self

    @property
    def connection_id(self) -> str:
        """Stable physical USB port path compatible with libsigrok."""
        if self.dev is None:
            raise HantekUSBError("Device is not open")
        ports = tuple(getattr(self.dev, "port_numbers", ()) or ())
        if not ports:
            port = getattr(self.dev, "port_number", None)
            ports = () if port is None else (int(port),)
        if not ports:
            raise HantekUSBError("Unable to determine USB physical port path")
        suffix = ".".join(str(int(port)) for port in ports)
        return f"usb/{int(self.dev.bus)}-{suffix}"

    def close(self):
        if self.dev is None:
            return
        if self._claimed:
            try:
                usb.util.release_interface(self.dev,INTERFACE)
            finally:
                self._claimed=False
        usb.util.dispose_resources(self.dev)
        self.dev=None

    def __enter__(self):
        return self.open()

    def __exit__(self,exc_type,exc,tb):
        self.close()

    def write(self,payload: bytes,*,timeout_ms=1000):
        if self.dev is None:
            raise HantekUSBError("Device is not open")
        try:
            return int(self.dev.write(EP_OUT,payload,timeout=timeout_ms))
        except usb.core.USBError as exc:
            raise HantekUSBError(f"USB write failed: {exc}") from exc

    def read(self,*,size=MAX_PACKET,timeout_ms=250):
        if self.dev is None:
            raise HantekUSBError("Device is not open")
        try:
            return bytes(self.dev.read(EP_IN,size,timeout=timeout_ms))
        except usb.core.USBTimeoutError:
            raise
        except usb.core.USBError as exc:
            raise HantekUSBError(f"USB read failed: {exc}") from exc

    def transact(self,payload: bytes,*,expect_reply=True,read_size=MAX_PACKET,read_timeout_ms=250,write_timeout_ms=1000):
        self.write(payload,timeout_ms=write_timeout_ms)
        rx=None
        timed_out=False
        if expect_reply:
            try:
                rx=self.read(size=read_size,timeout_ms=read_timeout_ms)
            except usb.core.USBTimeoutError:
                timed_out=True
        tx=Transaction(datetime.now(timezone.utc).isoformat(),bytes(payload),rx,timed_out)
        self._log(tx)
        return tx

    def _log(self,tx):
        if self.logger_path is None:
            return
        self.logger_path.parent.mkdir(parents=True,exist_ok=True)
        with self.logger_path.open('a',encoding='utf-8') as fh:
            json.dump(tx.as_dict(),fh,separators=(',',':'))
            fh.write('\n')
