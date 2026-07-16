from __future__ import annotations

import threading


# Provider profiles, provider secrets, and application settings form one local
# configuration graph. Mutations use one re-entrant lock so a concurrent
# settings save cannot reintroduce a provider while it is being deleted.
LOCAL_CONFIG_WRITE_LOCK = threading.RLock()
