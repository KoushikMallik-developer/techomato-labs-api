"""
Server-side OAuth 2.0 authorization-code exchange for Google and GitHub.

The SPA sends the user to the provider, receives `?code=...` on its redirect
URI, and POSTs that code (plus the redirect URI it used) to
/api/v1/auth/oauth/<provider>/. The client secret never leaves the server.
"""
from dataclasses import dataclass

import requests
from django.conf import settings


class OAuthError(Exception):
    """The provider rejected the code or returned an unusable identity."""


class OAuthNotConfigured(Exception):
    """Client id/secret for this provider are not set."""


@dataclass(frozen=True)
class Identity:
    provider: str
    uid: str
    email: str
    email_verified: bool
    name: str


GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
GITHUB_TOKEN_URL = 'https://github.com/login/oauth/access_token'
GITHUB_USER_URL = 'https://api.github.com/user'
GITHUB_EMAILS_URL = 'https://api.github.com/user/emails'


def credentials(provider):
    conf = settings.OAUTH_PROVIDERS.get(provider)
    if conf is None:
        raise KeyError(provider)
    if not conf.get('client_id') or not conf.get('client_secret'):
        raise OAuthNotConfigured(provider)
    return conf['client_id'], conf['client_secret']


def enabled_providers():
    return {
        name: conf['client_id']
        for name, conf in settings.OAUTH_PROVIDERS.items()
        if conf.get('client_id') and conf.get('client_secret')
    }


def _request(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=settings.OAUTH_HTTP_TIMEOUT, **kwargs)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OAuthError(str(exc)) from exc


def _google(code, redirect_uri):
    client_id, client_secret = credentials('google')
    token = _request(
        'POST',
        GOOGLE_TOKEN_URL,
        data={
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        },
    )
    access_token = token.get('access_token')
    if not access_token:
        raise OAuthError('No access token returned.')
    info = _request('GET', GOOGLE_USERINFO_URL, headers={'Authorization': f'Bearer {access_token}'})
    if not info.get('sub') or not info.get('email'):
        raise OAuthError('Google did not return an email address.')
    return Identity(
        provider='google',
        uid=str(info['sub']),
        email=info['email'].lower(),
        email_verified=bool(info.get('email_verified')),
        name=info.get('name') or info['email'].split('@')[0],
    )


def _github(code, redirect_uri):
    client_id, client_secret = credentials('github')
    token = _request(
        'POST',
        GITHUB_TOKEN_URL,
        headers={'Accept': 'application/json'},
        data={'client_id': client_id, 'client_secret': client_secret, 'code': code, 'redirect_uri': redirect_uri},
    )
    access_token = token.get('access_token')
    if not access_token:
        raise OAuthError(token.get('error_description') or 'No access token returned.')
    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'}
    user = _request('GET', GITHUB_USER_URL, headers=headers)
    emails = _request('GET', GITHUB_EMAILS_URL, headers=headers)
    primary = next((e for e in emails if e.get('primary') and e.get('verified')), None)
    if not user.get('id') or not primary:
        raise OAuthError('GitHub did not return a verified primary email address.')
    return Identity(
        provider='github',
        uid=str(user['id']),
        email=primary['email'].lower(),
        email_verified=True,
        name=user.get('name') or user.get('login') or primary['email'].split('@')[0],
    )


_FETCHERS = {'google': _google, 'github': _github}


def fetch_identity(provider, code, redirect_uri):
    """Exchange an authorization code for the provider's view of the user."""
    return _FETCHERS[provider](code, redirect_uri)
