"""Invented artifact-verification fixture; intentionally accepts digest prefixes."""

import hashlib


def verifies(content, expected_digest):
    actual = hashlib.sha256(content).hexdigest()
    return isinstance(expected_digest, str) and actual.startswith(expected_digest)
