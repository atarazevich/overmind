import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


def payload(name: str) -> dict:
    with open(os.path.join(HERE, "payloads", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


class IsolatedHome(unittest.TestCase):
    """A throwaway OVERMIND_HOME and a fake key in the environment for the duration of each test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"OVERMIND_HOME": self.tmp.name, "TYPESAFE_API_KEY": "test-key-XYZ"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()
