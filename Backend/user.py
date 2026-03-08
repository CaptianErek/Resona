import logging
import bcrypt
from sqlalchemy.exc import IntegrityError
from database import Session, User
from schema import UserInfo


logger = logging.getLogger(__name__)


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class Users:
    def new_user(self, userinfo: UserInfo) -> dict:
        session = Session()
        try:
            provider = userinfo.provider.casefold()
            existing_user = (
                session.query(User)
                .filter_by(name=userinfo.name, email=userinfo.email, provider=provider)
                .first()
            )
            if existing_user is not None:
                logger.info(
                    "Registration blocked: user exists",
                    extra={"email": userinfo.email, "provider": provider},
                )
                raise ServiceError(409, "User already exists")

            if provider == "default":
                if userinfo.password is None:
                    raise ServiceError(400, "Password required for default provider")
                password_bytes = userinfo.password.encode("utf-8")
                hash_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
                user = User(
                    name=userinfo.name,
                    email=userinfo.email,
                    password=hash_password,
                    provider=provider,
                )
            elif provider == "google":
                if not userinfo.provider_id:
                    raise ServiceError(400, "provider_id required for google provider")
                user = User(
                    name=userinfo.name,
                    email=userinfo.email,
                    provider_id=userinfo.provider_id,
                    provider=provider,
                )
            else:
                raise ServiceError(400, "Unsupported provider")

            session.add(user)
            session.commit()
            logger.info(
                "User created successfully",
                extra={"email": userinfo.email, "provider": provider},
            )
            return {"name": user.name, "email": user.email, "provider": user.provider}
        except IntegrityError:
            session.rollback()
            logger.warning(
                "Registration failed due to unique constraint",
                extra={"email": userinfo.email},
            )
            raise ServiceError(409, "User already exists")
        except ServiceError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            logger.exception("Unexpected error while creating user")
            raise ServiceError(500, "Internal server error")
        finally:
            session.close()

    def login_user(self, userinfo: UserInfo) -> dict:
        session = Session()
        try:
            provider = userinfo.provider.casefold()
            check_user = (
                session.query(User)
                .filter_by(email=userinfo.email, provider=provider)
                .first()
            )
            if check_user is None:
                logger.info("Login failed: user not found", extra={"email": userinfo.email})
                raise ServiceError(404, "User not found")

            if check_user.name != userinfo.name: # type: ignore
                logger.warning(
                    "Login failed: name mismatch",
                    extra={"email": userinfo.email, "provider": provider},
                )
                raise ServiceError(401, "Invalid credentials")

            if provider == "default":
                if userinfo.password is None or check_user.password is None:
                    logger.warning("Login failed: missing password", extra={"email": userinfo.email})
                    raise ServiceError(401, "Invalid credentials")
                if not bcrypt.checkpw(userinfo.password.encode("utf-8"), check_user.password): # type: ignore
                    logger.warning("Login failed: bad password", extra={"email": userinfo.email})
                    raise ServiceError(401, "Invalid credentials")
            elif provider == "google":
                if not userinfo.provider_id or userinfo.provider_id != check_user.provider_id:
                    logger.warning(
                        "Login failed: provider id mismatch",
                        extra={"email": userinfo.email, "provider": provider},
                    )
                    raise ServiceError(401, "Invalid credentials")

            logger.info("Login successful", extra={"email": userinfo.email})
            return {
                "name": check_user.name,
                "email": check_user.email,
                "provider": check_user.provider,
            }
        except ServiceError:
            raise
        except Exception:
            logger.exception("Unexpected error while logging in user")
            raise ServiceError(500, "Internal server error")
        finally:
            session.close()
