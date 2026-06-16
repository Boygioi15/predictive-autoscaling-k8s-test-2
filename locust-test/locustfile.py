import os
import logging


def _configure_logging() -> None:
    suppress_pool_warnings = os.getenv("SUPPRESS_URLLIB3_POOL_WARNINGS", "true").split()[0].lower()
    if suppress_pool_warnings in {"1", "true", "yes", "on"}:
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)


_configure_logging()

from users.prime_user import PrimeUser
from users.text_user import TextUser


class PrimeWebsiteUser(PrimeUser):
    weight = int(os.getenv("PRIME_USER_WEIGHT", 1))


class TextWebsiteUser(TextUser):
    weight = int(os.getenv("TEXT_USER_WEIGHT", 2))
