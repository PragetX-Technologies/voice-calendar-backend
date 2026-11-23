"""
One-time script to get a Google OAuth2 refresh token for calendar access.

Setup (once, in Google Cloud Console):
1. Create/select a project -> APIs & Services -> enable "Google Calendar API"
2. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
   -> Application type: Desktop app
3. Download the client secret JSON, save it as client_secret.json next to
   this script (or pass its path as the first CLI arg)

Run:
    python scripts/google_oauth_setup.py [path/to/client_secret.json]

A browser window opens, ask you to sign in and grant calendar access.
Copy the printed GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
into your .env.
"""
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main():
    # default: client_secret.json next to this script (git-ignored), regardless of where you run it from
    client_secret_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("client_secret.json"))
    if not Path(client_secret_path).is_file():
        sys.exit(f"Client secret file not found: {client_secret_path}\nDownload it from Google Cloud -> Credentials -> your Desktop OAuth client -> Download JSON, "
                 "then save it there or pass its path:  python scripts/google_oauth_setup.py \"C:/path/to/client_secret_xxx.json\"")

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\nAdd these to your .env:\n")
    print(f"GOOGLE_CLIENT_ID={creds.client_id}")
    print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
