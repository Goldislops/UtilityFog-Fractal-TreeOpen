"""OMI-V1 - explicit allowlist registry binding a name to a capability + factory.

The registry is the *only* place a candidate becomes reachable. It exists to
make three properties structural rather than aspirational:

  1. **Explicit allowlisting.** A ``BackendRegistry`` is constructed with the
     exact set of names that may ever be registered against it. A name outside
     that set is refused, so a candidate cannot appear by accident, by import
     side effect, or by data supplied at run time.

  2. **No arbitrary executable or endpoint injection.** No method here accepts
     a URL, host, port, command, argument vector, credential, or environment
     value. A backend is supplied as an already-constructed *factory callable*
     that an operator wrote and a reviewer read. There is no string in this
     module that is ever spawned, connected to, imported by name, or eval'd.

  3. **Metadata is not approval.** Registering a descriptor is not enough to
     use it. ``create()`` refuses any backend whose descriptor does not
     *separately* assert ``availability == "present"`` - an assertion only an
     operator who actually observed the backend can make honestly. A
     catalogue entry, which never asserts availability, is therefore inert.

The ``AgentBackend`` import is taken from ``scripts.agent_backends.base``
rather than from the ``scripts.agent_backends`` package root on purpose: the
package root lazily imports the ``anthropic`` and ``openai`` SDKs, and this
layer must stay importable with no third-party dependency present at all.
"""

from __future__ import annotations

from typing import Callable, Final, Iterable

from scripts.agent_backends.base import AgentBackend
from scripts.open_model.capabilities import ModelCapabilities


BackendFactory = Callable[[], AgentBackend]
"""A zero-argument callable an operator supplies to construct a backend.

Zero-argument on purpose: there is no parameter through which a caller could
inject an endpoint, a command line, or a credential at routing time. Whatever
configuration a real backend needs is closed over by the operator-authored
factory, in code that a reviewer reads.
"""


class RegistrationRefused(Exception):
    """A registration was refused. ``reason`` carries a stable code.

    The supplied value is never echoed into the message - only a fixed reason
    code - so a refusal cannot leak a credential, path, or prompt fragment
    that was mistakenly passed in.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BackendUnavailable(Exception):
    """Construction was refused. ``reason`` carries a stable code.

    As with ``RegistrationRefused``, no supplied value is echoed.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_NAME_MAX_LEN: Final[int] = 128


class BackendRegistry:
    """Ordered, allowlisted map of name -> (capabilities, factory).

    Registration order is preserved and is the tie-breaker for routing, so
    the same inputs always produce the same decision.
    """

    def __init__(self, *, allowed_names: Iterable[str]) -> None:
        """Build a registry that will accept only ``allowed_names``.

        A name is admitted to the allowlist only when it is exactly built-in
        ``str`` and non-empty; every other shape is dropped without invoking
        any hook on it. An empty allowlist is legal and means "nothing may
        ever register here" - the maximally fail-closed configuration, and
        the correct one for a deployment with no operator-approved backend.
        """
        admitted: list[str] = []
        if type(allowed_names) is tuple or type(allowed_names) is list:
            candidates: Iterable[object] = allowed_names
        elif type(allowed_names) is frozenset or type(allowed_names) is set:
            # Sort so the stored allowlist is order-stable regardless of the
            # set's iteration order, which varies with insertion history.
            candidates = sorted(
                element for element in allowed_names if type(element) is str
            )
        else:
            candidates = ()
        for element in candidates:
            if type(element) is not str:
                continue
            if not element or len(element) > _NAME_MAX_LEN:
                continue
            if element in admitted:
                continue
            admitted.append(element)
        self._allowed: frozenset[str] = frozenset(admitted)
        self._order: list[str] = []
        self._capabilities: dict[str, ModelCapabilities] = {}
        self._factories: dict[str, BackendFactory] = {}

    # -- introspection -------------------------------------------------------

    @property
    def allowed_names(self) -> tuple[str, ...]:
        """The allowlist, sorted, as a stable tuple."""
        return tuple(sorted(self._allowed))

    def names(self) -> tuple[str, ...]:
        """Registered names in registration order."""
        return tuple(self._order)

    def __contains__(self, name: object) -> bool:
        return type(name) is str and name in self._capabilities

    def __len__(self) -> int:
        return len(self._order)

    def capabilities_for(self, name: str) -> ModelCapabilities:
        """Descriptor registered under ``name``.

        Raises ``BackendUnavailable("name-not-registered")`` when absent.
        """
        if type(name) is not str or name not in self._capabilities:
            raise BackendUnavailable("name-not-registered")
        return self._capabilities[name]

    def registration_index(self, name: str) -> int:
        """Position of ``name`` in registration order; ``-1`` when absent."""
        if type(name) is not str:
            return -1
        if name not in self._capabilities:
            return -1
        return self._order.index(name)

    # -- mutation ------------------------------------------------------------

    def register(
        self,
        name: str,
        capabilities: ModelCapabilities,
        factory: BackendFactory,
    ) -> None:
        """Bind ``name`` to a descriptor and an operator-supplied factory.

        Refuses, with a stable reason code and no echo of the supplied value:

        - ``name-not-exact-str``      - name is not exactly built-in ``str``,
                                        is empty, or exceeds the length bound.
        - ``name-not-allowlisted``    - name is outside this registry's allowlist.
        - ``name-already-registered`` - re-registration is never silent; an
                                        operator changing a binding must build
                                        a new registry, so a live decision can
                                        never be altered underneath a caller.
        - ``capabilities-not-exact-type`` - not exactly a ``ModelCapabilities``
                                        (subclasses are refused; their
                                        properties could be overridden).
        - ``capabilities-missing-model-id`` - the descriptor normalized its
                                        ``model_id`` away, so it identifies
                                        nothing reviewable.
        - ``factory-not-callable``    - the factory is not callable.
        """
        if type(name) is not str or not name or len(name) > _NAME_MAX_LEN:
            raise RegistrationRefused("name-not-exact-str")
        if name not in self._allowed:
            raise RegistrationRefused("name-not-allowlisted")
        if name in self._capabilities:
            raise RegistrationRefused("name-already-registered")
        if type(capabilities) is not ModelCapabilities:
            raise RegistrationRefused("capabilities-not-exact-type")
        if not capabilities.model_id:
            raise RegistrationRefused("capabilities-missing-model-id")
        if not callable(factory):
            raise RegistrationRefused("factory-not-callable")
        self._order.append(name)
        self._capabilities[name] = capabilities
        self._factories[name] = factory

    # -- construction --------------------------------------------------------

    def create(self, name: str) -> AgentBackend:
        """Construct the backend registered under ``name``.

        This is the second of two independent gates. Routing already refuses
        a candidate whose availability is not ``"present"``; this refuses it
        again at construction time, so a caller that skips the router - or
        one that holds a decision computed before a descriptor was replaced -
        still cannot instantiate an unobserved backend.

        Refuses with a stable reason code:

        - ``name-not-registered``
        - ``availability-not-present`` - the descriptor does not assert that
          this backend was actually observed usable.
        - ``factory-returned-wrong-type`` - the operator factory did not
          return an ``AgentBackend``, so the seam contract is not satisfied.
        """
        if type(name) is not str or name not in self._factories:
            raise BackendUnavailable("name-not-registered")
        if self._capabilities[name].availability != "present":
            raise BackendUnavailable("availability-not-present")
        backend = self._factories[name]()
        if not isinstance(backend, AgentBackend):
            raise BackendUnavailable("factory-returned-wrong-type")
        return backend


__all__ = [
    "BackendFactory",
    "BackendRegistry",
    "BackendUnavailable",
    "RegistrationRefused",
]
