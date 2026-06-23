"""Thin acquisition bridge exports for non-runtime handoff owners."""

from .development_patch import record_development_patch_proposal, request_development_patch_handoff
from .v2_targets import (
    V2CapabilityActivationHooks,
    V2CapabilityRollbackHooks,
    validate_v2_activation_target_spec,
    validate_v2_target_specs,
)

__all__ = [
    "V2CapabilityActivationHooks",
    "V2CapabilityRollbackHooks",
    "record_development_patch_proposal",
    "request_development_patch_handoff",
    "validate_v2_activation_target_spec",
    "validate_v2_target_specs",
]
