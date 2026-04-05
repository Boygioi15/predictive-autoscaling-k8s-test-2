from users.prime_user import PrimeUser
from users.text_user import TextUser
import os

class PrimeWebsiteUser(PrimeUser):
    weight = int(os.getenv("PRIME_USER_WEIGHT", 1))

class TextWebsiteUser(TextUser):
    weight = int(os.getenv("TEXT_USER_WEIGHT", 2))

# Conditionally import and use the load shape
scenario = os.getenv("SCENARIO", "idle").lower()
if scenario != "none":
    from shapes import ScenarioShape
