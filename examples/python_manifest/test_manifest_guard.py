import hashlib
import unittest

from manifest_guard import verifies


class ManifestGuardTests(unittest.TestCase):
    def setUp(self):
        self.content = b"invented artifact\n"
        self.digest = hashlib.sha256(self.content).hexdigest()

    def test_exact_digest(self):
        self.assertTrue(verifies(self.content, self.digest))

    def test_prefix_refused(self):
        self.assertFalse(verifies(self.content, self.digest[:12]))

    def test_empty_refused(self):
        self.assertFalse(verifies(self.content, ""))

    def test_changed_content(self):
        self.assertFalse(verifies(self.content + b"changed", self.digest))

    def test_uppercase_refused(self):
        self.assertFalse(verifies(self.content, self.digest.upper()))

    def test_non_string_refused(self):
        self.assertFalse(verifies(self.content, None))
