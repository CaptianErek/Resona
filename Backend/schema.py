import re
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_STYLES = {"Interview", "Debate", "Casual Chat", "Storytelling"}


class UserInfo(BaseModel):
    name: str
    password: Optional[str] = None
    email: str
    provider: str
    provider_id: Optional[str] = None

    @field_validator("password", mode="before")
    @classmethod
    def normalize_password(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email_pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
        if not re.match(email_pattern, value):
            raise ValueError("Invalid email address format.")
        return value

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        accepted_values = ["default", "google"]
        normalized_value = value.casefold()
        if normalized_value not in accepted_values:
            raise ValueError(f"Provider must be in : {accepted_values}")
        return normalized_value

    @model_validator(mode="after")
    def validate_auth_fields(self) -> "UserInfo":
        if self.provider == "default":
            if self.password is None:
                raise ValueError("Password is required for default provider.")
            pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$"
            if not re.match(pattern, self.password):
                raise ValueError(
                    "Password must be at least 8 characters and include uppercase, lowercase, number, and special character."
                )
        if self.provider == "google" and self.password is not None and not self.password.strip():
            self.password = None
        return self


class Chat_Schema(BaseModel):
    url: str
    style: str
    exchanges: int
    user_email: str

    @field_validator("style")
    @classmethod
    def validate_style(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in VALID_STYLES:
            raise ValueError(f"Style must be one of: {sorted(VALID_STYLES)}")
        return normalized

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if not (parsed.scheme in ("https", "http") and parsed.netloc):
            raise ValueError("Invalid URL. Must include http/https and hostname.")
        return value

    @field_validator("exchanges")
    @classmethod
    def validate_exchanges(cls, value: int) -> int:
        if value < 2 or value > 40:
            raise ValueError("Exchanges must be between 2 and 40.")
        return value

    @field_validator("user_email")
    @classmethod
    def validate_user_email(cls, value: str) -> str:
        email_pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
        if not re.match(email_pattern, value):
            raise ValueError("Invalid user email format.")
        return value


class PodcastJobCreate(Chat_Schema):
    pass


class PodcastJobStatus(BaseModel):
    job_id: int
    status: Literal["queued", "in_progress", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    error: Optional[str] = None
    podcast_id: Optional[int] = None


class PodcastTurnEvent(BaseModel):
    type: Literal[
        "turn_started",
        "turn_text_ready",
        "turn_audio_ready",
        "job_completed",
        "job_failed",
    ]
    job_id: int
    turn_index: Optional[int] = None
    speaker: Optional[str] = None
    text: Optional[str] = None
    audio_chunk_url: Optional[str] = None
    podcast_id: Optional[int] = None
    error: Optional[str] = None


class PodcastArtifact(BaseModel):
    podcast_id: int
    script_download_url: Optional[str] = None
    audio_download_url: Optional[str] = None
    metadata: dict


class KeysCreate(BaseModel):
    useremail: str
    key_type: Literal["grok", "openrouter"]
    key_value: str

    @field_validator("useremail")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email_pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
        if not re.match(email_pattern, value):
            raise ValueError("Invalid email address format.")
        return value

    @field_validator("key_value")
    @classmethod
    def validate_key_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("key_value must not be empty.")
        return value
