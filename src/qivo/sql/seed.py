from abc import abstractmethod
from typing import Type

from sqlalchemy.orm import DeclarativeBase, Session


class BaseSeeder:
    name: str

    def __init__(self, session: Session):
        self.session = session

    @abstractmethod
    def run(self):
        raise NotImplementedError

    def first_or_create(self, obj: DeclarativeBase, match):
        db_obj = self.session.query(obj.__class__).filter(match).first()
        if db_obj is None:
            db_obj = obj
            self.session.add(db_obj)
        return db_obj

    def create_or_update(self, model: Type[DeclarativeBase], match, data: dict):
        db_obj = self.session.query(model).filter(match).first()
        if db_obj is None:
            obj = model(**data)
            self.session.add(obj)
            return obj
        else:
            self.session.query(model).filter(match).update(data)
        return db_obj
