from users.prime_user import PrimeUser
from users.text_user import TextUser

class WebsiteUser(PrimeUser):
    weight = 2

class TextWebsiteUser(TextUser):
    weight = 2
