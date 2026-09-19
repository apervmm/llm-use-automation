from safety.allowlist import Allowlist, PolicyViolation
from safety.redaction import redact, redact_dict

allowlist = Allowlist()

# Should pass = parabank.soft is allowed
allowlist.check_action("navigate", url="https://parabank.parasoft.com/parabank/index.htm")
print("PASS: allowed domain accepted")

print()
print(50*"=")
print()

# Should raise off-allowlist domain
try:
    allowlist.check_action("navigate", url="https://evil.com/phish")
    print("FAIL: should have blocked")
except PolicyViolation as e:
    print("PASS: blocked disallowed domain —", e)

print()
print(50*"=")
print()

# Risk classification
print("is_risky('parabank.login'):", allowlist.is_risky("parabank.login"))  # False
print("is_risky('parabank.transfer_funds'):", allowlist.is_risky("parabank.transfer_funds"))  # True

print()
print(50*"=")
print()

# Redaction
print(redact("My SSN is 123-45-6789 and card is 4111111111111111"))
print(redact_dict({"username": "test", "password": "test"}))