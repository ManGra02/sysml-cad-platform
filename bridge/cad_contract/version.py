"""Contract version between bridge and backend.

Compared during the handshake. If it does not match, the backend reports this
clearly instead of failing on unexpected fields -- the most likely
failure with two separately deployed processes.

RULE: Every change to types.py or events.py bumps this version AND
adds a line to CHANGELOG.md, which the mismatch message refers to.
"""

CONTRACT_VERSION = "0.6.0"
