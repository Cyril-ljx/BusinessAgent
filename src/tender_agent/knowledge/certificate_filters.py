from datetime import date
from typing import Any

from sqlalchemy import or_


def usable_certificate_filters(model: Any) -> tuple[Any, ...]:
    """Return the shared filters used when certificates become bid material."""
    return (
        model.is_current.is_(True),
        model.deleted_at.is_(None),
        or_(model.expire_date.is_(None), model.expire_date >= date.today()),
    )
