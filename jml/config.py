import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Config:
    keycloak_url: str
    realm: str
    client_id: str
    client_secret: str
    database_url: str

    @classmethod
    def load_from_env(cls, env_path: Optional[str] = None) -> "Config":
        """
        Loads configuration settings from environment variables.
        Optionally parses a .env file if present.
        """
        if env_path and os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        elif os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())

        keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
        realm = os.getenv("REALM", "company")
        client_id = os.getenv("JML_CLIENT_ID", "jml-automation")
        client_secret = os.getenv("JML_CLIENT_SECRET", "jml-automation-secret-demo-123")
        database_url = os.getenv("DATABASE_URL", "postgresql://jml:jml123@localhost:5432/jml")

        missing = []
        if not keycloak_url:
            missing.append("KEYCLOAK_URL")
        if not realm:
            missing.append("REALM")
        if not client_id:
            missing.append("JML_CLIENT_ID")
        if not client_secret:
            missing.append("JML_CLIENT_SECRET")
        if not database_url:
            missing.append("DATABASE_URL")

        if missing:
            raise ValueError(
                f"Missing required environment variables for JML configuration: {', '.join(missing)}"
            )

        return cls(
            keycloak_url=keycloak_url,
            realm=realm,
            client_id=client_id,
            client_secret=client_secret,
            database_url=database_url,
        )
