"""Background job subsystem.

Phase 1: workers can run inside the API process (opt-in) so we can deploy quickly.
Phase 2: run workers as a separate service using the same code.
"""
