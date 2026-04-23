from __future__ import annotations

from contextvars import ContextVar
from typing import Any

current_org_id: ContextVar[str | None] = ContextVar("current_org_id", default=None)
current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
current_supabase: ContextVar[Any] = ContextVar("current_supabase", default=None)
