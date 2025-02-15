import asyncio
import concurrent
import contextlib
import dataclasses
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Tuple, Type, TypeVar

from starkware.python.utils import from_bytes, to_bytes
from starkware.starkware_utils.config_base import get_object_by_path
from starkware.starkware_utils.serializable import Serializable
from starkware.starkware_utils.validated_dataclass import ValidatedDataclass

HASH_BYTES = 32
HashFunctionType = Callable[[bytes, bytes], Awaitable[bytes]]
TIntToIntMapping = TypeVar("TIntToIntMapping", bound="IntToIntMapping")


class Storage(ABC):
    """
    This is a base storage class, all storage classes should inherit from it.
    """

    @staticmethod
    async def create_instance_from_config(config: Dict[str, Any], logger=None) -> "Storage":
        """
        Creates a Storage instance from a config dictionary.
        """
        storage_class = get_object_by_path(path=config["class"])
        if hasattr(storage_class, "create_from_config"):
            storage_instance = await storage_class.create_from_config(**config["config"])
        else:
            storage_instance = storage_class(**config.get("config", {}))
        assert isinstance(storage_instance, Storage)
        if logger is not None:
            logger.info(f"Instance of {type(storage_instance)} was created.")
        return storage_instance

    @abstractmethod
    async def set_value(self, key: bytes, value: bytes):
        pass

    @abstractmethod
    async def get_value(self, key: bytes) -> Optional[bytes]:
        pass

    @abstractmethod
    async def del_value(self, key: bytes):
        pass

    async def mset(self, updates: Dict[bytes, bytes]):
        await asyncio.gather(*(self.set_value(*item) for item in updates.items()))

    async def mget(self, keys: Sequence[bytes]) -> Tuple[Optional[bytes], ...]:
        return tuple(await asyncio.gather(*(self.get_value(key) for key in keys)))

    async def set_int(self, key: bytes, value: int):
        assert isinstance(key, bytes)
        assert isinstance(value, int)
        value_bytes = str(value).encode("ascii")
        await self.set_value(key, value_bytes)

    async def setnx_int(self, key: bytes, value: int) -> bool:
        assert isinstance(key, bytes)
        assert isinstance(value, int)
        value_bytes = str(value).encode("ascii")
        return await self.setnx_value(key, value_bytes)

    async def get_int(self, key: bytes, default=None) -> Optional[int]:
        assert isinstance(key, bytes)
        result = await self.get_value(key)
        return default if result is None else int(result)

    async def set_float(self, key: bytes, value: float):
        assert isinstance(key, bytes)
        assert isinstance(value, float)
        value_bytes = str(value).encode("ascii")
        await self.set_value(key, value_bytes)

    async def setnx_float(self, key: bytes, value: float) -> bool:
        assert isinstance(key, bytes)
        assert isinstance(value, float)
        value_bytes = str(value).encode("ascii")
        return await self.setnx_value(key, value_bytes)

    async def get_float(self, key: bytes, default=None) -> Optional[float]:
        assert isinstance(key, bytes)
        result = await self.get_value(key)
        return default if result is None else float(result)

    async def set_str(self, key: bytes, value: str):
        assert isinstance(key, bytes)
        assert isinstance(value, str)
        value_bytes = value.encode("ascii")
        await self.set_value(key, value_bytes)

    async def setnx_str(self, key: bytes, value: str) -> bool:
        assert isinstance(key, bytes)
        assert isinstance(value, str)
        value_bytes = value.encode("ascii")
        return await self.setnx_value(key, value_bytes)

    async def get_str(self, key: bytes, default=None) -> Optional[str]:
        assert isinstance(key, bytes)
        result = await self.get_value(key)
        return default if result is None else result.decode("ascii")

    async def setnx_value(self, key: bytes, value: bytes) -> bool:
        raise NotImplementedError(f"{self.__class__.__name__} does not implement setnx_value")

    async def setnx_time(self, key: bytes, time: float):
        assert isinstance(key, bytes)
        assert isinstance(time, float)
        await self.setnx_float(key, time)

    async def get_time(self, key: bytes) -> Optional[float]:
        assert isinstance(key, bytes)
        return await self.get_float(key)


TDBObject = TypeVar("TDBObject", bound="DBObject")


class DBObject(Serializable):
    @classmethod
    def db_key(cls, suffix: bytes) -> bytes:
        return cls.prefix() + b":" + suffix

    @classmethod
    async def get(cls: Type[TDBObject], storage: Storage, suffix: bytes) -> Optional[TDBObject]:
        """
        Returns the value under key cls.db_key(suffix) in the storage.
        If key does not exist, returns None.
        """
        result = await storage.get_value(key=cls.db_key(suffix=suffix))

        if result is None:
            return None

        return cls.deserialize(data=result)

    @classmethod
    async def get_or_fail(cls: Type[TDBObject], storage: Storage, suffix: bytes) -> TDBObject:
        """
        Returns the value under key cls.db_key(suffix) in the storage.
        If key does not exist, raises an exception.
        """
        db_key = cls.db_key(suffix=suffix)
        result = await storage.get_value(key=db_key)
        assert result is not None, f"Key {db_key!r} does not appear in storage."

        return cls.deserialize(data=result)

    async def set(self, storage: Storage, suffix: bytes):
        await storage.set_value(self.db_key(suffix), self.serialize())

    async def setnx(self, storage: Storage, suffix: bytes) -> bool:
        return await storage.setnx_value(self.db_key(suffix), self.serialize())

    def get_update_for_mset(self, suffix: bytes) -> Tuple[bytes, bytes]:
        """
        Returns a (key, value) pair that can be converted to a dict for mset.

        Usage:
            storage.mset(updates=dict(
                *[obj.get_indexed_update_for_mset(suffix) for key, obj in obj_updates.items()],
            ))
        """
        return (self.db_key(suffix), self.serialize())


TIndexedDBObject = TypeVar("TIndexedDBObject", bound="IndexedDBObject")


class IndexedDBObject(DBObject):
    """
    A db object with integer key.
    """

    @classmethod
    def key(cls, index: int) -> bytes:
        return cls.db_key(str(index).encode("ascii"))

    @classmethod
    async def get_obj(
        cls: Type[TIndexedDBObject], storage: Storage, index: int
    ) -> Optional[TIndexedDBObject]:
        return await cls.get(storage, str(index).encode("ascii"))

    async def set_obj(self, storage: Storage, index: int):
        await self.set(storage, str(index).encode("ascii"))

    async def setnx_obj(self, storage: Storage, index: int) -> bool:
        return await self.setnx(storage, str(index).encode("ascii"))

    def get_indexed_update_for_mset(self, index: int) -> Tuple[bytes, bytes]:
        """
        Returns a (key, value) pair that can be converted to a dict for mset.

        Usage:
            storage.mset(updates=dict(
                *[obj.get_indexed_update_for_mset(index) for key, obj in obj_updates.items()],
            ))
        """
        return (self.key(index), self.serialize())


@dataclasses.dataclass(frozen=True)
class IntToIntMapping(ValidatedDataclass, IndexedDBObject):
    """
    Represents a mapping from integer key to integer value.
    """

    value: int

    def serialize(self) -> bytes:
        length = (self.value.bit_length() + 7) // 8  # Floor division.
        return to_bytes(value=self.value, length=length)

    @classmethod
    def deserialize(cls: Type[TIntToIntMapping], data: bytes) -> TIntToIntMapping:
        return cls(value=from_bytes(data))

    @classmethod
    async def get_value_or_fail(cls, storage: Storage, key: int) -> int:
        """
        Reads the value object from storage under the given key, and
        returns its corresponding value. Raises an error, if does not exist in storage.
        """
        value_db_object = await cls.get_obj(storage=storage, index=key)
        assert (
            value_db_object is not None
        ), f"{cls.__name__} value of key {key} does not appear in storage."

        return value_db_object.value

    @classmethod
    async def setnx_value(cls, storage: Storage, key: int, value: int) -> bool:
        return await cls(value=value).setnx_obj(storage=storage, index=key)


class FactFetchingContext:
    """
    Information needed to fetch and store facts from a storage.
    A user may provide different implementations to the hash function in here.
    """

    def __init__(
        self, storage: Storage, hash_func: HashFunctionType, n_workers: Optional[int] = None
    ):
        self.storage = storage
        self.hash_func = hash_func
        self.n_workers = n_workers

    def __repr__(self) -> str:
        return (
            f"{type(self)}(storage={self.storage!r}, hash_func={self.hash_func!r}, "
            f"n_workers={self.n_workers!r})"
        )


class Fact(DBObject):
    """
    A fact is a DB object with a DB key that is a hash of its value.
    Use set_fact() and get() to read and write facts.
    """

    @abstractmethod
    async def _hash(self, hash_func: HashFunctionType) -> bytes:
        pass

    async def set_fact(self, ffc: FactFetchingContext) -> bytes:
        hash_val = await self._hash(ffc.hash_func)
        await self.set(storage=ffc.storage, suffix=hash_val)
        return hash_val


class LockError(Exception):
    pass


class LockObject(ABC):
    @abstractmethod
    async def extend(self):
        pass

    @abstractmethod
    async def __aenter__(self) -> "LockObject":
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc, tb):
        pass


class LockManager(ABC):
    @staticmethod
    async def create_instance_from_config(config: Dict[str, Any], logger=None) -> "LockManager":
        """
        Creates a LockManager instance from a config dictionary.
        """
        lock_manager_class = get_object_by_path(path=config["class"])
        lock_manager_instance = lock_manager_class(**config["config"])
        if logger is not None:
            logger.info(f"Created instance of {type(lock_manager_instance)}")
        assert isinstance(lock_manager_instance, LockManager)
        return lock_manager_instance

    @staticmethod
    @contextlib.asynccontextmanager
    async def from_config_context(config, logger=None):
        lock_manager = await LockManager.create_instance_from_config(config=config, logger=logger)
        try:
            yield lock_manager
        finally:
            await lock_manager.destroy()

    @abstractmethod
    async def lock(self, name: str) -> LockObject:
        pass

    @abstractmethod
    async def try_lock(self, name: str, ttl: int = None) -> LockObject:
        pass

    async def destroy(self):
        pass


@contextlib.contextmanager
def distributed_hash_function(hash_function: HashFunctionType, n_hash_workers: int):
    with concurrent.futures.ProcessPoolExecutor(max_workers=n_hash_workers) as pool:

        async def async_hash_funcion(x, y):
            return await asyncio.get_event_loop().run_in_executor(pool, hash_function, x, y)

        yield async_hash_funcion
