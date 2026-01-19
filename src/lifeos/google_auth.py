import argparse
import json
import logging
import os
from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

log = logging.getLogger(__name__)

DEFAULT_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _get_token_path() -> Path:
    token_path = os.getenv("GOOGLE_TOKEN_PATH", ".secrets/google_token.json")
    return Path(token_path).expanduser()


def _load_client_config() -> dict:
    client_secret_path = os.getenv("GOOGLE_CLIENT_SECRET_PATH", "client_secret.json")
    secret_path = Path(client_secret_path).expanduser()
    if secret_path.exists():
        with secret_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if client_id and client_secret:
        redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
        config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": (
                    [redirect_uri] if redirect_uri else ["http://localhost"]
                ),
            }
        }
        return config

    raise RuntimeError(
        "Google OAuth client secrets not found. Set GOOGLE_CLIENT_SECRET_PATH or "
        "GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET."
    )


def _load_credentials(token_path: Path, scopes: Sequence[str]) -> Credentials | None:
    if not token_path.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(token_path), scopes=scopes)
    if not creds.scopes:
        return None

    if not set(scopes).issubset(set(creds.scopes)):
        log.warning("Stored Google credentials missing required scopes")
        return None

    return creds


def _save_credentials(token_path: Path, creds: Credentials) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def get_credentials(
    scopes: Sequence[str], allow_oauth: bool = False, force: bool = False
) -> Credentials:
    token_path = _get_token_path()
    creds = None if force else _load_credentials(token_path, scopes)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(token_path, creds)

    if creds and creds.valid:
        return creds

    if not allow_oauth:
        raise RuntimeError(
            "Google OAuth credentials missing. Run `lifeos-google-auth` to authenticate."
        )

    config = _load_client_config()
    flow = InstalledAppFlow.from_client_config(config, scopes=scopes)
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if redirect_uri:
        flow.redirect_uri = redirect_uri

    try:
        run_console = getattr(flow, "run_console", None)
        if callable(run_console):
            creds = run_console()
        else:
            creds = flow.run_local_server(port=0, open_browser=True)
    except Exception as exc:
        log.warning("Falling back to manual OAuth flow: %s", exc)
        auth_url, _ = flow.authorization_url(prompt="consent")
        print("Authorize this app by visiting this URL:")
        print(auth_url)
        code = input("Enter the authorization code: ").strip()
        flow.fetch_token(code=code)
        creds = flow.credentials
    _save_credentials(token_path, creds)
    return creds


def authenticate(scopes: Sequence[str], force: bool = False) -> Credentials:
    return get_credentials(scopes, allow_oauth=True, force=force)


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticate Google OAuth locally.")
    parser.add_argument(
        "--scopes",
        help="Comma-separated OAuth scopes. Defaults to Calendar read/write scopes.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore any saved credentials and re-authenticate.",
    )
    args = parser.parse_args()

    if args.scopes:
        scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    else:
        scopes = DEFAULT_CALENDAR_SCOPES

    authenticate(scopes, force=args.force)
    token_path = _get_token_path()
    print(f"Google OAuth complete. Token saved to {token_path}")


if __name__ == "__main__":
    main()
