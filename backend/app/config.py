from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_reasoning_model: str = Field(default="gpt-5.5", alias="OPENAI_REASONING_MODEL")
    openai_coding_model: str = Field(default="gpt-5.1-codex-max", alias="OPENAI_CODING_MODEL")
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_owner: str | None = Field(default=None, alias="GITHUB_OWNER")
    github_repo: str | None = Field(default=None, alias="GITHUB_REPO")
    github_base_branch: str = Field(default="main", alias="GITHUB_BASE_BRANCH")
    discord_webhook_url: str | None = Field(default=None, alias="DISCORD_WEBHOOK_URL")
    desktop_voice_enabled: bool = Field(default=True, alias="DESKTOP_VOICE_ENABLED")

    root_dir: Path = Path(__file__).resolve().parents[2]
    runtime_dir: Path = root_dir / "runtime"
    db_path: Path = runtime_dir / "devpilot.sqlite3"
    sample_repo_path: Path = root_dir / "sample-repo"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    return settings
