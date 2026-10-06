import os

# user_profiles (internal API, см. docs/user_profiles_contract.md §2)
PROFILES_SERVICE_URL = 'http://user_profiles:8000'
PROFILES_SERVICE_TIMEOUT = float(os.getenv('PROFILES_SERVICE_TIMEOUT', '3'))
PROFILES_INTERNAL_API_KEY = os.getenv('PROFILES_INTERNAL_API_KEY', '')
