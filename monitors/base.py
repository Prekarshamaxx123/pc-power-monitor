"""
Base interface and abstractions for hardware power and metrics monitors.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from monitors.models import ComponentPower


class BaseMonitor(ABC):
    """Abstract base class that all subsystem monitors must implement."""

    def __init__(self, name: str):
        self.name = name
        self.is_initialized: bool = False
        self.last_reading: Optional[ComponentPower] = None
        self._warnings: List[str] = []

    @abstractmethod
    def initialize(self) -> bool:
        """
        Detect hardware, verify sysfs/command interfaces, and check permissions.
        Returns True if the monitor can provide readings (measured or estimated),
        False if the component is entirely absent or disabled.
        """
        pass

    @abstractmethod
    def read(self, elapsed_s: float) -> Optional[ComponentPower]:
        """
        Collect current metrics and compute power consumption in Watts.
        elapsed_s: elapsed time in seconds since the last sample or session start.
        """
        pass

    def get_warnings(self) -> List[str]:
        """Return any active warnings (permission issues, fallback notices, missing files)."""
        return list(self._warnings)

    def clear_warnings(self) -> None:
        """Clear transient warnings."""
        self._warnings.clear()

    def cleanup(self) -> None:
        """Release any open file descriptors, sockets, or background handles."""
        pass
