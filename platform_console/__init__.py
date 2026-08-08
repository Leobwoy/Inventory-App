"""The console for whoever runs TrackTrack.

Deliberately not part of the tenant application. Everything in `auth/` answers
"what may this person do inside their business"; nothing here is about a
business at all - it is about the platform the businesses sit on.

Kept separate in three ways that matter:

- **Its own table.** A platform admin is not a User, so they need no business,
  and the rule that every user belongs to a tenant stays absolute.
- **Its own session key.** A tenant session cannot become a platform session,
  because no code reads across. Signing in as an Owner grants nothing here.
- **Its own layout.** No tenant sidebar, no plan gates - none of it applies.
"""
from flask import Blueprint

platform_bp = Blueprint('platform', __name__, url_prefix='/platform',
                        template_folder='../templates/platform')

from . import routes  # noqa: E402,F401
