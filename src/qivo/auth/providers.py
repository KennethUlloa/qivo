import jwt

from datetime import datetime, timedelta


class JWTProvider:
    def __init__(
        self,
        secret_key: str,
        access_key_expire: int,
        refresh_key_expire: int,
        algorithm: str,
    ):
        self.secret_key = secret_key
        self.access_key_expire = access_key_expire
        self.refresh_key_expire = refresh_key_expire
        self.algorithm = algorithm

    def access_key(self, identity, **content) -> str:
        expires = datetime.now() + timedelta(seconds=self.access_key_expire)

        payload = {"sub": identity, "exp": expires.timestamp(), "type": "access"}
        payload.update(content)

        return jwt.encode(
            payload,
            self.secret_key,
            self.algorithm,
        )

    def refresh_key(self, identity, **content) -> str:
        expires = datetime.now() + timedelta(seconds=self.refresh_key_expire)

        payload = {"sub": identity, "exp": expires.timestamp(), "type": "refresh"}
        payload.update(content)

        return jwt.encode(
            payload,
            self.secret_key,
            self.algorithm,
        )

    def payload(self, token: str) -> dict:
        return jwt.decode(token, self.secret_key, [self.algorithm])
