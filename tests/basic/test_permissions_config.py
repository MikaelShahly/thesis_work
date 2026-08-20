"""Static checks on the permission wiring.

These tests don't exercise the SDK — they confirm the project is
*shaped* the way the permission system expects:

- Every phase declares a `permission_mode`. If the key is missing, the
  phase handler silently falls back to "default" via `.get()`, which
  hides config drift; we catch it here.
- `Bash` is not pre-approved on any phase. Allow-listing Bash would
  bypass `can_use_tool` and silently re-introduce unprompted shell
  execution — exactly the regression we built this gate to prevent.
- The permission registry exposes the trio of API functions the rest
  of the codebase imports (`register`, `resolve_allow`, `resolve_deny`).
"""

from src.agent import permissions
from src.config import PHASE_CONFIGS


def test_every_phase_declares_permission_mode():
    missing = [
        name for name, cfg in PHASE_CONFIGS.items()
        if "permission_mode" not in cfg
    ]
    assert not missing, f"phases missing permission_mode: {missing}"


def test_bash_is_never_pre_approved():
    # `allowed_tools` is the auto-approve list (anything in `tools` but
    # not in `allowed_tools` routes through can_use_tool). Bash sitting
    # in `tools` is fine — that just makes the model aware it exists —
    # but it must never appear in `allowed_tools`.
    leaks = [
        name for name, cfg in PHASE_CONFIGS.items()
        if "Bash" in cfg.get("allowed_tools", [])
    ]
    assert not leaks, f"phases pre-approving Bash (must be gated): {leaks}"


def test_permissions_module_surface():
    for fn in ("register", "unregister", "resolve_allow", "resolve_deny"):
        assert callable(getattr(permissions, fn, None)), f"missing {fn}"
    assert isinstance(permissions.DENY_MESSAGE, str)
    assert permissions.DENY_MESSAGE  # non-empty
