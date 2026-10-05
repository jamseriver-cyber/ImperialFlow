import json
from pathlib import Path

from .errors import require
from .models import Action, Role


CAPABILITIES_PATH = Path(__file__).parents[1] / "schemas" / "role_capabilities.json"
CAPABILITIES = json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))


def validate_role_action(role: Role | str, action: Action | str):
    require(str(action) in CAPABILITIES.get(str(role), []),
            "ROLE_CAPABILITY_VIOLATION", f"{role} cannot {action}")
