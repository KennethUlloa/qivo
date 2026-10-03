from dataclasses import dataclass

from sqlalchemy.orm import DeclarativeBase, Query


@dataclass
class Paginated:
    page: int
    per_page: int
    items: list
    total: int

    @classmethod
    def get(cls, query: Query, page: int, per_page: int):
        return cls(
            page=page,
            per_page=per_page,
            items=query.offset((page - 1) * per_page).limit(per_page).all(),
            total=query.count(),
        )

    @property
    def has_next(self):
        return self.page * self.per_page < self.total

    def to_dict(self):
        return {
            "page": self.page,
            "per_page": self.per_page,
            "items": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.items
            ],
            "total": self.total,
            "has_next": self.has_next,
        }

def ensure_list(value):
    if not isinstance(value, list):
        return [value]
    return value

def to_dict(model: DeclarativeBase):
    excluded = ensure_list(getattr(model, "__exclude__", []))
    included = ensure_list(getattr(model, "__include__", []))

    if not isinstance(excluded, list):
        excluded = []

    data = {k: getattr(model, k) for k, v in model.__table__.c.items() if k not in excluded}

    if included:
        data.update({k: getattr(model, k) for k in included})

    return data