import logging
from typing import Any, Dict, Optional

import cachetools

from starkware.storage import metrics
from starkware.storage.storage import Storage


class DictStorage(Storage):
    """
    Local storage using dict.
    """

    def __init__(self, db=None):
        if db is None:
            db = {}
        self.db = db

    async def set_value(self, key: bytes, value: bytes):
        self.db[key] = value

    async def get_value(self, key: bytes) -> Optional[bytes]:
        return self.db.get(key, None)

    async def del_value(self, key: bytes):
        try:
            del self.db[key]
        except KeyError:
            pass


class CachedStorage(Storage):
    def __init__(self, storage: Storage, max_size: int, metric_active: bool = False):
        self.storage = storage
        self.cache = cachetools.LRUCache(maxsize=max_size)
        self.metric_active = metric_active

    @classmethod
    async def create_from_config(
        cls, config: Dict[str, Any], logger: Optional[logging.Logger] = None
    ) -> "CachedStorage":
        return cls(
            storage=await Storage.create_instance_from_config(config=config["storage"]),
            max_size=config["max_size"],
            metric_active=config["metric_active"],
        )

    async def set_value(self, key: bytes, value: bytes):
        self.cache[key] = value
        await self.storage.set_value(key, value)

    async def get_value(self, key: bytes) -> Optional[bytes]:
        if self.metric_active:
            metrics.CACHED_STORAGE_GET_TOTAL.inc()
        if key in self.cache:
            if self.metric_active:
                metrics.CACHED_STORAGE_GET_CACHE.inc()
            return self.cache[key]
        value = await self.storage.get_value(key)
        if value is None:
            return None
        self.cache[key] = value
        return value

    async def del_value(self, key: bytes):
        raise NotImplementedError("CachedStorage is expected to handle only immutable items")
