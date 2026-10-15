"""Obtain a Gmail API refresh token for GmailAPIEmailBackend (run locally).

Runs Google's OAuth "installed app" flow with a loopback redirect: a tiny
HTTP server listens on 127.0.0.1, your browser opens Google's consent page,
and after you approve, the authorisation code is exchanged for tokens.

Only the refresh token is printed. Nothing is written to disk.

Usage (PowerShell):
    $env:GMAIL_CLIENT_ID = "<Desktop OAuth client id>"
    $env:GMAIL_CLIENT_SECRET = "<Desktop OAuth client secret>"
    python scripts/get_gmail_refresh_token.py

Sign in with the Gmail account that should send the portal's email, then set
GMAIL_REFRESH_TOKEN on Render to the printed value. See docs/RUNBOOK.md.

Requires only `requests` (already in requirements.txt).
"""

import base64
import hashlib
import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser

import requests

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/gmail.send'
TIMEOUT = 10  # seconds


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures the ?code=... (or ?error=...) Google redirects back with."""

    result = {}

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if 'code' not in query and 'error' not in query:
            # Ignore unrelated requests such as /favicon.ico.
            self.send_response(404)
            self.end_headers()
            return
        type(self).result = {key: values[0] for key, values in query.items()}
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(
            b'<h2>Authorisation received.</h2>'
            b'<p>You can close this tab and return to the terminal.</p>'
        )

    def log_message(self, format, *args):
        # Keep the authorisation code out of the terminal.
        pass


def main():
    client_id = os.environ.get('GMAIL_CLIENT_ID', '').strip()
    client_secret = os.environ.get('GMAIL_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret:
        sys.exit('Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in the environment first.')

    server = http.server.HTTPServer(('127.0.0.1', 0), _CallbackHandler)
    redirect_uri = 'http://127.0.0.1:{}/'.format(server.server_address[1])

    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('ascii')).digest()
    ).decode('ascii').rstrip('=')

    auth_url = AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': SCOPE,
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
    })

    print('Opening the Google consent page in your browser.', file=sys.stderr)
    print('If it does not open, visit this URL:\n\n{}\n'.format(auth_url), file=sys.stderr)
    webbrowser.open(auth_url)

    try:
        while not _CallbackHandler.result:
            server.handle_request()
    except KeyboardInterrupt:
        sys.exit('Cancelled.')
    finally:
        server.server_close()

    result = _CallbackHandler.result
    if 'error' in result:
        sys.exit('Google returned an error: {}'.format(result['error']))
    if result.get('state') != state:
        sys.exit('State mismatch; aborting. Run the script again.')

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                'grant_type': 'authorization_code',
                'code': result['code'],
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri,
                'code_verifier': code_verifier,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        sys.exit('Token request failed: {}'.format(type(exc).__name__))

    if response.status_code != 200:
        try:
            error = response.json().get('error', 'unknown_error')
        except ValueError:
            error = 'unknown_error'
        sys.exit('Token exchange failed (HTTP {}): {}'.format(response.status_code, error))

    refresh_token = response.json().get('refresh_token')
    if not refresh_token:
        sys.exit(
            'Google did not return a refresh token. Remove the app at '
            'https://myaccount.google.com/permissions and run the script again.'
        )

    print(refresh_token)


if __name__ == '__main__':
    main()
