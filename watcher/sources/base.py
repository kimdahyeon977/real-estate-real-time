from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import WatchConfig
from ..models import Listing


class Source(ABC):
    @abstractmethod
    def fetch(self, watch: WatchConfig) -> list[Listing]:
        raise NotImplementedError

