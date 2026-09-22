import os

class Settings:
    app_env: str = os.environ.get("APP_ENV", "development")
    app_origin: str = os.environ["APP_ORIGIN"]
    google_client_id: str = os.environ["GOOGLE_CLIENT_ID"]
    app_signing_key: str = os.environ["APP_SIGNING_KEY"]

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"

settings = Settings()