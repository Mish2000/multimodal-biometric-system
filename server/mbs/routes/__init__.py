"""The API's routes by area, each module with its routes and their request models; mbs/api.py assembles them."""

from . import account, administration, faces, fingerprints, voices

ROUTERS = (account.router, fingerprints.router, faces.router, voices.router, administration.router)
BODY_LIMITS = {**faces.BODY_LIMITS, **voices.BODY_LIMITS}  # H58: the routes that take images or recordings
