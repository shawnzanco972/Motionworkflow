"""Provider registry. Add a provider by subclassing base.Provider and listing it here."""
from __future__ import annotations

from .base import AmbiguousError, Provider, ProviderError, RejectedError, StillRunning
from .enhancor import EnhancorProvider
from .fal import FalProvider
from .local import MockProvider, PollinationsProvider
from .replicate import ReplicateProvider

_REGISTRY: dict[str, Provider] = {
    p.name: p
    for p in (FalProvider(), ReplicateProvider(), EnhancorProvider(), PollinationsProvider(), MockProvider())
}


def get(name: str) -> Provider:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ProviderError(f"No provider named '{name}'.") from None


def register(provider: Provider) -> None:
    _REGISTRY[provider.name] = provider


__all__ = ["get", "register", "Provider", "ProviderError", "RejectedError", "AmbiguousError", "StillRunning"]
