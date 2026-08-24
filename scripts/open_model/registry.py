"""OMI-V1 - explicit allowlist registry binding a name to a capability + factory.

The registry is the *only* place a candidate becomes reachable. It exists to
make three properties structural rather than aspirational:

  1. **Explicit allowlisting.** A ``BackendRegistry`` is constructed with the
     exact set of names that may ever be registered against it. A name outside
     that set is refused, so a candidate cannot appear by accident, by import
     side effect, or by data supplied at run time.

  2. **No endpoint injection through this API — a bounded claim.** No method
     here accepts a URL, host, port, command, argument vector, credential, or
     environment value, and no string in this module is ever spawned,
     connected to, imported by name, or eval'd. That is a statement about
     *this API surface*, and it is all it was ever entitled to be.

     **It does not extend to what an operator-written factory closes over.**
     A factory is arbitrary code; it can construct a backend pointed at a
     paid remote endpoint while its descriptor claims ``locality="local"``,
     and no amount of care in this module can make that impossible. The
     original wording implied a structural guarantee here that did not
     exist; the audit was right, and the claim is now bounded to what is
     actually enforced.

     What *is* enforced, in two layers:

     - **A gate.** Registering a descriptor that claims ``local`` requires an
       explicit ``locality_attestation="operator-asserted"`` argument at the
       registration site. The trust is therefore named, in code, where a
       reviewer reads it - rather than being implied by a descriptor field.
     - **A best-effort detector.** ``create()`` inspects the constructed
       backend for a ``base_url``-shaped attribute and refuses when a
       ``local`` descriptor produced a backend pointed at a non-loopback
       host. This catches the concrete case that exists in this repository
       (``OpenAICompatBackend`` holds an SDK client with ``base_url``) and
       any backend following the same convention. It is **not** universal: a
       backend that reaches the network by some other route, or that hides
       its endpoint, is not detected. Detection failure is silent by
       necessity - absence of evidence, not evidence of locality.

     The residual guarantee is therefore an operator assertion, recorded at
     the registration site and cross-checked where the shape permits. It is
     not a structural proof, and this module no longer claims to be one.

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

from typing import Callable, Final, Iterable, Literal

from scripts.agent_backends.base import AgentBackend
from scripts.open_model.capabilities import ModelCapabilities
from scripts.open_model.redaction import (
    CONSTRUCTION_REFUSAL_REASONS,
    REGISTRATION_REFUSAL_REASONS,
    is_safe_token,
)


BackendFactory = Callable[[], AgentBackend]
"""A zero-argument callable an operator supplies to construct a backend.

Zero-argument on purpose: there is no parameter through which a caller could
inject an endpoint, a command line, or a credential at routing time. Whatever
configuration a real backend needs is closed over by the operator-authored
factory, in code that a reviewer reads.
"""


class RegistrationRefused(Exception):
    """A registration was refused. ``reason`` is a closed-vocabulary code.

    The supplied value is never echoed into the message - only a fixed reason
    code - so a refusal cannot leak a credential, path, or prompt fragment
    that was mistakenly passed in.
    """

    def __init__(self, reason: str) -> None:
        code = (
            reason
            if type(reason) is str and reason in REGISTRATION_REFUSAL_REASONS
            else "invalid-reason"
        )
        super().__init__(code)
        self.reason = code


class BackendUnavailable(Exception):
    """Construction was refused. ``reason`` is a closed-vocabulary code.

    Closed at the constructor, not merely at the call sites in this module,
    because an **operator-written factory** can raise this exception itself
    and the evaluation harness persists ``reason`` into a stored record.
    Without normalization here, a factory could write arbitrary text - a
    credential, a path, a prompt fragment - straight into evidence.

    Anything outside ``CONSTRUCTION_REFUSAL_REASONS`` becomes
    ``"invalid-reason"``, and the supplied value is retained nowhere: not on
    the instance, and not in the exception message, since the normalized code
    is what is passed to ``super().__init__``.
    """

    def __init__(self, reason: str) -> None:
        code = (
            reason
            if type(reason) is str and reason in CONSTRUCTION_REFUSAL_REASONS
            else "invalid-reason"
        )
        super().__init__(code)
        self.reason = code


_NAME_MAX_LEN: Final[int] = 128

LocalityAttestation = Literal["operator-asserted", "not-required"]
"""Whether an operator has explicitly vouched for a ``local`` descriptor.

``"operator-asserted"`` is a named, reviewable claim by the person writing
the registration: *I have confirmed this factory constructs a backend that
executes locally.* ``"not-required"`` is only valid for descriptors that do
not claim ``locality="local"``.
"""

_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1", "[0:0:0:0:0:0:0:1]"}
)

_ENDPOINT_ATTRIBUTES: Final[tuple[str, ...]] = ("base_url", "_base_url", "endpoint")
_CLIENT_ATTRIBUTES: Final[tuple[str, ...]] = ("_client", "client")


def _host_of(url: str) -> str:
    """Extract the host from a URL by string slicing only.

    Hand-parsed rather than routed through ``urllib.parse`` so this module
    keeps importing nothing that can perform I/O - a property the boundary
    audit checks. Lowercased; userinfo and port are stripped.
    """
    remainder = url
    marker = remainder.find("://")
    if marker != -1:
        remainder = remainder[marker + 3 :]
    for terminator in ("/", "?", "#"):
        cut = remainder.find(terminator)
        if cut != -1:
            remainder = remainder[:cut]
    at_sign = remainder.rfind("@")
    if at_sign != -1:
        remainder = remainder[at_sign + 1 :]
    if remainder.startswith("["):
        close = remainder.find("]")
        if close != -1:
            return remainder[: close + 1].lower()
    colon = remainder.rfind(":")
    if colon != -1:
        remainder = remainder[:colon]
    return remainder.lower()


def _is_loopback(host: str) -> bool:
    """True for loopback names and the whole 127.0.0.0/8 range.

    ``0.0.0.0`` is deliberately **not** loopback: it means "every interface",
    which is the opposite of the property being checked.
    """
    if host in _LOOPBACK_HOSTS:
        return True
    if host.endswith(".localhost"):
        return True
    if host.startswith("127."):
        octets = host.split(".")
        if len(octets) == 4 and all(
            part.isdigit() and 0 <= int(part) <= 255 for part in octets
        ):
            return True
    return False


def detect_endpoint_host(backend: object) -> str:
    """Best-effort host of a constructed backend, or ``""`` when undetectable.

    Looks for a ``base_url``-shaped attribute directly on the backend, then
    on a held SDK client. Every read is wrapped, and a value is used only
    when it is exactly built-in ``str`` or renders to one through an
    SDK URL object whose ``str`` is safe to take.

    Returning ``""`` means *not detected*, which is not the same as *local*.
    Callers must treat it as unknown.
    """
    candidates: list[object] = [backend]
    for attribute in _CLIENT_ATTRIBUTES:
        held = getattr(backend, attribute, None)
        if held is not None:
            candidates.append(held)
    for candidate in candidates:
        for attribute in _ENDPOINT_ATTRIBUTES:
            value = getattr(candidate, attribute, None)
            if value is None:
                continue
            if type(value) is str:
                return _host_of(value)
            # SDK URL objects (e.g. httpx.URL) are not str but render to one.
            rendered = getattr(value, "host", None)
            if type(rendered) is str and rendered:
                return rendered.lower()
            try:
                text = str(value)
            except Exception:
                continue
            if type(text) is str and text:
                return _host_of(text)
    return ""


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
            # Allowlist entries must themselves be safe tokens: a name that
            # reaches a routing decision or an evaluation record must not be
            # able to carry a path, a URL, or secret-shaped text.
            if not is_safe_token(element, max_len=_NAME_MAX_LEN):
                continue
            if element in admitted:
                continue
            admitted.append(element)
        self._allowed: frozenset[str] = frozenset(admitted)
        self._order: list[str] = []
        self._capabilities: dict[str, ModelCapabilities] = {}
        self._factories: dict[str, BackendFactory] = {}
        self._attestations: dict[str, str] = {}

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

    def attestation_for(self, name: str) -> str:
        """The locality attestation recorded for ``name`` at registration."""
        if type(name) is not str or name not in self._attestations:
            raise BackendUnavailable("name-not-registered")
        return self._attestations[name]

    def register(
        self,
        name: str,
        capabilities: ModelCapabilities,
        factory: BackendFactory,
        *,
        locality_attestation: LocalityAttestation = "not-required",
    ) -> None:
        """Bind ``name`` to a descriptor and an operator-supplied factory.

        Refuses, with a stable reason code and no echo of the supplied value:

        - ``name-not-safe-token``     - the name is not a safe token:
                                        wrong type, empty, over-long, outside
                                        the closed character class, or
                                        secret-shaped. Names flow into routing
                                        decisions and stored records, so they
                                        are gated like any other persisted
                                        identifier.
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
        - ``locality-attestation-required`` - the descriptor claims
                                        ``locality="local"`` but the caller
                                        did not pass
                                        ``locality_attestation="operator-asserted"``.
        - ``locality-attestation-not-applicable`` - an attestation was passed
                                        for a descriptor that does not claim
                                        ``local``, which would misrepresent
                                        what was vouched for.
        """
        if not is_safe_token(name, max_len=_NAME_MAX_LEN):
            raise RegistrationRefused("name-not-safe-token")
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
        # A `local` claim must be vouched for explicitly, at the registration
        # site, by the person who can actually check it. See the module
        # docstring for why this is a gate rather than a proof.
        if capabilities.locality == "local":
            if locality_attestation != "operator-asserted":
                raise RegistrationRefused("locality-attestation-required")
        elif locality_attestation != "not-required":
            raise RegistrationRefused("locality-attestation-not-applicable")
        self._order.append(name)
        self._capabilities[name] = capabilities
        self._factories[name] = factory
        self._attestations[name] = locality_attestation

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
        # Best-effort cross-check of the operator's locality attestation.
        # An empty host means "not detected", which is NOT "local" - so this
        # refuses only on positive evidence of a remote endpoint, and never
        # claims to have proven locality when it finds nothing.
        if self._capabilities[name].locality == "local":
            host = detect_endpoint_host(backend)
            if host and not _is_loopback(host):
                raise BackendUnavailable("locality-mismatch-detected")
        return backend


__all__ = [
    "BackendFactory",
    "BackendRegistry",
    "BackendUnavailable",
    "LocalityAttestation",
    "RegistrationRefused",
    "detect_endpoint_host",
]
