"""
Verifies artifact versioning: saving a capability under an ID that already
has a saved version must produce a NEW version file, and the old version
must remain byte-for-byte unchanged and still loadable by number.

No browser/LLM calls — exercises store.save()/load() directly.
"""
from cua.artifact import store
from cua.artifact.schema import Capability, Checkpoint

CAP_ID = "verify.versioning.demo"

# Clean slate for this test id, so re-runs don't accumulate stale versions.
for p in store.ARTIFACT_DIR.glob(f"{CAP_ID}.v*.json"):
    p.unlink()

cap_v1 = Capability(
    capability_id=CAP_ID,
    entry_url="https://example.com/one",
    checkpoint=Checkpoint(kind="url_contains", expected="/one"),
)
path1 = store.save(cap_v1)
print(f"Saved: {path1.name} (version={cap_v1.version})")
assert path1.name == f"{CAP_ID}.v1.json"
original_v1_content = path1.read_text()

# Simulates re-recording the same capability id with a slightly different
# discovery run — this used to silently overwrite v1.
cap_v2_attempt = Capability(
    capability_id=CAP_ID,
    entry_url="https://example.com/one-updated",
    checkpoint=Checkpoint(kind="url_contains", expected="/one-updated"),
)
path2 = store.save(cap_v2_attempt)
print(f"Saved: {path2.name} (version={cap_v2_attempt.version})")
assert path2.name == f"{CAP_ID}.v2.json"
assert path1 != path2

v1_after = path1.read_text()
assert v1_after == original_v1_content, "v1 was mutated — overwrite still happening!"
print("PASS: v1 file is byte-for-byte unchanged after v2 was saved.")

latest = store.load(CAP_ID)
assert latest.version == 2 and latest.entry_url == "https://example.com/one-updated"
print("PASS: load(capability_id) with no version returns the latest (v2).")

original = store.load(CAP_ID, version=1)
assert original.version == 1 and original.entry_url == "https://example.com/one"
print("PASS: load(capability_id, version=1) still returns the original v1 content.")

for p in store.ARTIFACT_DIR.glob(f"{CAP_ID}.v*.json"):
    p.unlink()
print("\nCleaned up test artifacts.")