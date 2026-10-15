import os

# Tests opt into the unauthenticated presentation surface explicitly. Production
# and ordinary local startup default to authenticated administration.
os.environ.setdefault("DEMO_MODE", "true")
