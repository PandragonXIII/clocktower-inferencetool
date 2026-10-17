"""Backend adaptation layer between the web protocol and the reasoning engine.

This package defines the adapter contract used by the web backend to translate
protocol requests (`web/protocol`) into engine inputs and to translate engine
results back into protocol responses.

Only the framework lives here. No concrete Z3-based reasoning is wired up yet;
`PlaceholderAdapter` exists solely to exercise the contract.
"""

from .adapter import (
    PreparedRequest,
    PlaceholderAdapter,
    ReasoningAdapter,
)

__all__ = [
    "PreparedRequest",
    "PlaceholderAdapter",
    "ReasoningAdapter",
]
