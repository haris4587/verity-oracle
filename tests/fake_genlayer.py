"""
Minimal in-process stand-in for the GenLayer `genlayer` SDK.

The real SDK only exists inside the GenVM execution environment. This stub
implements just enough of its surface — decorators, storage primitives,
u256 arithmetic, the nondeterminism bridge, and EVM transfers — to import
`contracts/verity_oracle.py` and exercise its settlement logic in plain
Python. It is intentionally small; behavior not needed by the tests is
left unimplemented.
"""

import json
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Balance bookkeeping so emit_transfer tests are real
# ---------------------------------------------------------------------------

class _Vault:
    def __init__(self) -> None:
        self.balances: dict[int, int] = {}
        self.current_contract: int | None = None
        self.transfers: list[dict[str, Any]] = []

    def register(self, key: int) -> None:
        self.balances[key] = 0
        self.current_contract = key

    def credit(self, key: int, amount: int) -> None:
        self.balances[key] = self.balances.get(key, 0) + amount

    def send(self, to_address: str, amount: int) -> None:
        assert self.current_contract is not None
        assert self.balances[self.current_contract] >= amount, "insufficient balance"
        self.balances[self.current_contract] -= amount
        self.transfers.append({
            "from_contract": self.current_contract,
            "to": to_address,
            "amount": amount,
        })


VAULT = _Vault()


# ---------------------------------------------------------------------------
# Integer types
# ---------------------------------------------------------------------------

class _Uint:
    BITS = 256

    def __init__(self, value: Any = 0) -> None:
        if isinstance(value, _Uint):
            value = value.v
        self.v = int(value)
        if self.v < 0 or self.v >= 2 ** self.BITS:
            raise ValueError("integer out of range")

    def _peer(self, other: Any) -> int:
        return other.v if isinstance(other, _Uint) else int(other)

    def __int__(self) -> int:
        return self.v

    def __index__(self) -> int:
        return self.v

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.v})"

    def __hash__(self) -> int:
        return hash(self.v)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _Uint):
            return self.v == other.v
        if isinstance(other, int):
            return self.v == other
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __lt__(self, other: Any) -> bool:
        return self.v < self._peer(other)

    def __le__(self, other: Any) -> bool:
        return self.v <= self._peer(other)

    def __gt__(self, other: Any) -> bool:
        return self.v > self._peer(other)

    def __ge__(self, other: Any) -> bool:
        return self.v >= self._peer(other)

    def __add__(self, other: Any) -> "_Uint":
        return type(self)(self.v + self._peer(other))

    def __radd__(self, other: Any) -> "_Uint":
        return type(self)(self._peer(other) + self.v)

    def __iadd__(self, other: Any) -> "_Uint":
        self.v += self._peer(other)
        return self

    def __sub__(self, other: Any) -> "_Uint":
        return type(self)(self.v - self._peer(other))

    def __isub__(self, other: Any) -> "_Uint":
        self.v -= self._peer(other)
        return self

    def __floordiv__(self, other: Any) -> "_Uint":
        return type(self)(self.v // self._peer(other))

    def __ifloordiv__(self, other: Any) -> "_Uint":
        self.v //= self._peer(other)
        return self

    def __mul__(self, other: Any) -> "_Uint":
        return type(self)(self.v * self._peer(other))


class u256(_Uint):
    BITS = 256


class u128(_Uint):
    BITS = 128


class u64(_Uint):
    BITS = 64


class u32(_Uint):
    BITS = 32


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

class Address:
    def __init__(self, value: Any) -> None:
        if isinstance(value, Address):
            self.hex = value.hex
        else:
            self.hex = str(value)

    @property
    def as_hex(self) -> str:
        return self.hex

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Address):
            return self.hex.lower() == other.hex.lower()
        if isinstance(other, str):
            return self.hex.lower() == other.lower()
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.hex.lower())

    def __repr__(self) -> str:
        return f"Address({self.hex})"


# ---------------------------------------------------------------------------
# Storage primitives
# ---------------------------------------------------------------------------

class TreeMap(dict):
    def get(self, key: Any, default: Any = None) -> Any:
        return dict.get(self, key, default)

    def get_or_insert_default(self, key: Any) -> Any:
        if key not in self:
            self[key] = u256(0)
        return self[key]


class DynArray(list):
    def append(self, item: Any) -> None:
        list.append(self, item)


def allow_storage(cls: type) -> type:
    return cls


# ---------------------------------------------------------------------------
# Message context
# ---------------------------------------------------------------------------

class _Message:
    def __init__(self) -> None:
        self.sender_address: Address = Address("0x0000000000000000000000000000000000000000")
        self.value: u256 = u256(0)
        self.data: bytes = b""


# ---------------------------------------------------------------------------
# Nondeterministic bridge
# ---------------------------------------------------------------------------

class Return:
    def __init__(self, calldata: Any) -> None:
        self.calldata = calldata


class UserError(Exception):
    pass


# When set, the second adjudication call (the validator's independent rerun)
# receives this verdict from exec_prompt instead, letting tests exercise the
# disagreement path.
VALIDATOR_DIVERGENCE: dict[str, Any] | None = None


class _VM:
    UserError = UserError
    Return = Return

    @staticmethod
    def run_nondet_unsafe(leader: Callable[[], Any], validator: Callable[[Any], bool]) -> Any:
        global VALIDATOR_DIVERGENCE
        leader_result = leader()
        if VALIDATOR_DIVERGENCE is not None:
            snapshot = VALIDATOR_DIVERGENCE
            VALIDATOR_DIVERGENCE = None
            previous = _nondet._exec_override
            def _diverging(prompt: str, response_format: str | None = None) -> Any:
                merged = dict(snapshot)
                return merged
            _nondet._exec_override = _diverging
            try:
                accepted = validator(Return(leader_result))
            finally:
                _nondet._exec_override = previous
        else:
            accepted = validator(Return(leader_result))
        if not accepted:
            raise RuntimeError("validator rejected leader result (no consensus)")
        return leader_result


class _Response:
    def __init__(self, status: int, body: bytes, headers: dict | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}


# Test harness: route fixture URLs to canned bytes.
WEB_FIXTURES: dict[str, _Response | Exception] = {}


class _Web:
    @staticmethod
    def get(url: str, **kwargs: Any) -> _Response:
        if url not in WEB_FIXTURES:
            raise RuntimeError(f"no fixture for {url}")
        fixture = WEB_FIXTURES[url]
        if isinstance(fixture, Exception):
            raise fixture
        return fixture

    @staticmethod
    def head(url: str, **kwargs: Any) -> _Response:
        return _Web.get(url, **kwargs)


class _Nondet:
    def __init__(self) -> None:
        self._exec_override: Callable[[str, str | None], Any] | None = None
        # Default jury: tests usually set this per case.
        self.default_verdict: dict[str, Any] = {
            "verdict": "UNRESOLVABLE",
            "confidence_band": "LOW",
            "evidence_quality": 0,
            "rationale": "default fake jury",
            "citations": [],
        }

    def exec_prompt(self, prompt: str, response_format: str | None = None) -> Any:
        if self._exec_override is not None:
            return self._exec_override(prompt, response_format)
        return dict(self.default_verdict)


_nondet = _Nondet()


# ---------------------------------------------------------------------------
# EVM bridge
# ---------------------------------------------------------------------------

def contract_interface(cls: type) -> type:
    """Inject the GenVM-style constructor and transfer emitter."""

    def __init__(self: Any, address: Any) -> None:
        self._address = address

    def emit_transfer(self: Any, value: Any) -> None:
        addr = self._address
        hex_addr = addr.as_hex if isinstance(addr, Address) else str(addr)
        VAULT.send(hex_addr, int(value))

    cls.__init__ = __init__  # type: ignore[method-assign]
    cls.emit_transfer = emit_transfer  # type: ignore[attr-defined]
    return cls


# ---------------------------------------------------------------------------
# Contract base
# ---------------------------------------------------------------------------

class Contract:
    def __new__(cls, *args: Any, **kwargs: Any) -> "Contract":
        instance = super().__new__(cls)
        VAULT.register(id(instance))
        # GenVM pre-allocates every annotated storage slot before __init__.
        for name, annotation in cls.__dict__.get("__annotations__", {}).items():
            origin = getattr(annotation, "__origin__", None)
            if origin is TreeMap:
                setattr(instance, name, TreeMap())
            elif origin is DynArray:
                setattr(instance, name, DynArray())
        return instance

    @property
    def balance(self) -> u256:
        return u256(VAULT.balances.get(id(self), 0))


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

class _WriteDecorator:
    def __call__(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn

    def payable(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn


class _Public:
    @staticmethod
    def view(fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn

    write = _WriteDecorator()


class _Equivalence:
    @staticmethod
    def strict_eq(fn: Callable[[], Any]) -> Any:
        return fn()

    @staticmethod
    def prompt_comparative(fn: Callable[[], Any], principle: str) -> Any:
        return fn()

    @staticmethod
    def prompt_non_comparative(fn: Callable[[], Any], task: str = "", criteria: str = "") -> Any:
        return fn()


class _EVM:
    contract_interface = staticmethod(contract_interface)


class _Gl:
    Contract = Contract
    Address = Address
    TreeMap = TreeMap
    DynArray = DynArray
    allow_storage = staticmethod(allow_storage)
    public = _Public()
    message = _Message()
    vm = _VM()
    nondet = _nondet
    nondet.web = _Web  # type: ignore[attr-defined]
    eq_principle = _Equivalence()
    evm = _EVM()
    coin = None  # unused by Verity


gl = _Gl()
