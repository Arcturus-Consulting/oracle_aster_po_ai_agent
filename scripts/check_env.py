import os
from dotenv import load_dotenv

load_dotenv()

password = os.getenv("ORACLE_PASSWORD", "")

print("ORACLE_BASE_URL =", os.getenv("ORACLE_BASE_URL"))
print("ORACLE_AUTH_MODE =", os.getenv("ORACLE_AUTH_MODE"))
print("ORACLE_USERNAME =", os.getenv("ORACLE_USERNAME"))
print("ORACLE_PASSWORD length =", len(password))
print("ORACLE_PASSWORD contains # =", "#" in password)
print("ORACLE_PASSWORD starts with quote =", password.startswith(("'", '"')))