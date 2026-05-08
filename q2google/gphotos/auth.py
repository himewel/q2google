"""OAuth helpers for Google Photos Library API using installed-app credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .models import PhotosScopes


@dataclass
class GooglePhotosOAuth:
    """Load, refresh, or obtain Google OAuth credentials for Photos scopes.

    Attributes:
        client_secrets_file: Path to the Google OAuth client secrets JSON (installed app).
        scopes: API scopes to request; values are sent to the authorization server.
        token_file: Optional path to persist the authorized user token; parent dirs are
            created on save. If omitted, tokens are only kept in memory.
    """

    client_secrets_file: str
    scopes: list[PhotosScopes]
    token_file: str | None = None

    def _save_token(self, creds: Credentials) -> None:
        """Serialize credentials to ``token_file`` if configured.

        Args:
            creds: Credentials to persist as JSON.
        """
        if self.token_file is None:
            return

        parent = os.path.dirname(self.token_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    def load_saved_credentials(self) -> Credentials | None:
        """Load credentials from disk and refresh if expired.

        Returns:
            Valid or refreshed credentials, or ``None`` if there is no token file,
            if ``RefreshError`` occurs during refresh (the token file is then removed),
            or if stored credentials cannot be used.
        """
        if self.token_file is None or not os.path.isfile(self.token_file):
            return None

        creds = Credentials.from_authorized_user_file(self.token_file)
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
            except RefreshError:
                try:
                    os.unlink(self.token_file)
                except OSError:
                    pass
                return None
        return creds

    def authorize_interactive(self) -> Credentials:
        """Run the local-server OAuth flow and optionally persist the token.

        Returns:
            Newly authorized credentials.
        """
        flow = InstalledAppFlow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=[s.value for s in self.scopes],
        )
        creds = flow.run_local_server(open_browser=False)
        if self.token_file is not None:
            self._save_token(creds)
        return creds

    def ensure_credentials(self) -> Credentials:
        """Return stored valid credentials, or complete an interactive authorization.

        Returns:
            Credentials that are valid for API calls (refreshed from disk when possible).

        Raises:
            Various ``google_auth`` exceptions: If the OAuth flow or refresh fails in a way not
                handled by :meth:`load_saved_credentials`.
        """
        saved = self.load_saved_credentials()
        if saved is not None and saved.valid:
            return saved
        return self.authorize_interactive()
