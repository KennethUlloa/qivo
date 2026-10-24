import pytest
from werkzeug.exceptions import Forbidden, Unauthorized

class User:
    def __init__(self, permissions):
        self.permissions = permissions

    def get_id(self):
        return "1"

    def get_permissions(self):
        return self.permissions


