"""Every endpoint over loopback against a temp OVERMIND_HOME, CLAUDE_CONFIG_DIR and vendor dir. No network, no key."""
import http.client
import json
import os
import stat
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock
from urllib.parse import quote

from overmind import dashboard, log
from tests import IsolatedHome

TS = "2026-09-17T19:00:0%d.000+00:00"
JSON = {"Content-Type": "application/json"}


class Endpoint(IsolatedHome):
    def setUp(self) -> None:
        super().setUp()
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp.name, "claude")  # restored by IsolatedHome's patch
        os.makedirs(dashboard.sessions_dir())
        self.vendor = mock.patch.object(dashboard, "VENDOR", os.path.join(self.tmp.name, "vendor"))
        self.vendor.start()
        self.quiet = mock.patch.object(dashboard.Handler, "log_request")  # 4xx probes below would spam stderr
        self.quiet.start()
        os.makedirs(dashboard.VENDOR)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.vendor.stop()
        self.quiet.stop()
        super().tearDown()

    def call(self, method: str, path: str, body: bytes = None, headers: dict = None) -> tuple:
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        self.assertEqual(resp.getheader("Cache-Control"), "no-store", path)
        if resp.getheader("Content-Type", "").startswith("application/json"):
            data = json.loads(data)
        return resp.status, data

    def post_label(self, **fields) -> tuple:
        return self.call("POST", "/label", json.dumps(fields).encode(), JSON)

    def seed(self) -> None:
        """Two judged Stops and one error line."""
        for i, prob in enumerate([0.9, 0.2]):
            line = log.event_line("jev-1.13.0", 800, 500, {"needs_owner": prob, "stuck": 0.1},
                                  event="Stop", session_id="sid", cwd="demo")
            line["ts"] = TS % i
            log.append(line)
        log.append(log.error_line("Stop", "sid", "no_key"))


class Static(Endpoint):
    def test_root_serves_the_page(self) -> None:
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Overmind", body)

    def test_vendor_serves_only_files_directly_inside(self) -> None:
        with open(os.path.join(dashboard.VENDOR, "plotly.min.js"), "w") as f:
            f.write("window.Plotly={}")
        os.makedirs(os.path.join(dashboard.VENDOR, "sub"))
        open(os.path.join(dashboard.VENDOR, "sub", "x.js"), "w").close()
        os.symlink(log.events_path(), os.path.join(dashboard.VENDOR, "link.js"))
        log.append({"secret": 1})
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        conn.request("GET", "/vendor/plotly.min.js")
        resp = conn.getresponse()
        self.assertEqual((resp.status, resp.getheader("Content-Type"), resp.read()),
                         (200, "application/javascript", b"window.Plotly={}"))
        conn.close()
        for path in ("/vendor/missing.js", "/vendor/sub/x.js", "/vendor/", "/vendor/../dashboard.html",
                     "/vendor/link.js", "/vendor/" + quote(os.path.join("..", "..", "log.py"))):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_unknown_paths(self) -> None:
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/summary")[0], 404)
        self.assertEqual(self.call("POST", "/events", b"{}", JSON)[0], 404)


class Events(Endpoint):
    def test_events_since_limit_and_errors(self) -> None:
        self.assertEqual(self.call("GET", "/events"), (200, []))
        self.seed()
        status, lines = self.call("GET", "/events")
        self.assertEqual(status, 200)
        self.assertEqual([x.get("error") for x in lines], [None, None, "no_key"])
        since = "/events?since=" + quote(TS % 0)  # the client encodes '+' as %2B, as encodeURIComponent does
        self.assertEqual([x.get("ts") for x in self.call("GET", since)[1]][:1], [TS % 1])
        self.assertEqual(len(self.call("GET", since)[1]), 2)
        self.assertEqual(self.call("GET", "/events?limit=1")[1][0]["error"], "no_key")
        for bad in ("x", "0", "-5"):
            self.assertEqual(self.call("GET", "/events?limit=" + bad)[0], 400, bad)

    def test_v1_lines_are_still_served_and_still_labelable(self) -> None:
        """A day of v1 lines is already on disk; schema v2 may not orphan them."""
        v1 = {"ts": TS % 0, "v": 1, "event": "Stop", "session_id": "sid", "cwd": "demo",
              "model": "jev-1.13.0", "ms": 800, "input_tokens": 500,
              "answers": {"needs_owner": 0.91}, "state_source": "payload"}
        log.append(v1)
        log.append(log.event_line("jev-1.13.0", 800, 500, {"jumped": 0.4},
                                  {"depth": 3, "tool_calls": 2}, event="Stop", session_id="sid",
                                  cwd="demo"))
        self.assertEqual([x["v"] for x in self.call("GET", "/events")[1]], [1, 2])
        status, line = self.post_label(event_ts=TS % 0, session_id="sid",
                                       question="needs_owner", label="y")
        self.assertEqual((status, line["prob"]), (200, 0.91))

    def test_the_opted_in_state_passes_through_only_when_the_line_has_it(self) -> None:
        state = {"command": "rm -rf build", "cwd": "demo"}
        log.append({"ts": TS % 0, "session_id": "a", "answers": {"risky": 0.9}})
        log.append({"ts": TS % 1, "session_id": "b", "answers": {"risky": 0.9}, "state": state})
        lines = self.call("GET", "/events")[1]
        self.assertEqual([x.get("state") for x in lines], [None, state])


class Sessions(Endpoint):
    def test_sessions_skips_unreadable_and_non_json(self) -> None:
        files = {"1.json": json.dumps({"pid": 1, "sessionId": "s-1", "name": "voice", "cwd": "/v", "status": "idle"}),
                 "2.json": "{not json", "3.json": "[1]", "4.json": json.dumps({"pid": 4}), "1.key": "secret"}
        for name, text in files.items():
            with open(os.path.join(dashboard.sessions_dir(), name), "w", encoding="utf-8") as f:
                f.write(text)
        self.assertEqual(self.call("GET", "/sessions"),
                         (200, [{"session_id": "s-1", "name": "voice", "cwd": "/v", "status": "idle"}]))

    def test_sessions_without_dir(self) -> None:
        os.rmdir(dashboard.sessions_dir())
        self.assertEqual(self.call("GET", "/sessions"), (200, []))


class Label(Endpoint):
    GOOD = {"event_ts": TS % 0, "session_id": "sid", "question": "needs_owner", "label": "y"}

    def test_label_stores_the_events_probability_0600_and_lists(self) -> None:
        self.seed()
        status, line = self.post_label(**self.GOOD, prob=0.55)  # the client's number is ignored
        self.assertEqual(status, 200)
        self.assertEqual(list(line), ["ts", "event_ts", "session_id", "question", "prob", "label"])
        self.assertEqual(line["prob"], 0.9)
        self.assertEqual(stat.S_IMODE(os.stat(log.labels_path()).st_mode), 0o600)
        self.post_label(**dict(self.GOOD, label="n"))
        self.post_label(**dict(self.GOOD, event_ts=TS % 1, question="stuck", label="s"))
        self.assertEqual([(x["label"], x["prob"]) for x in self.call("GET", "/labels")[1]],
                         [("y", 0.9), ("n", 0.9), ("s", 0.1)])
        self.assertEqual(len(log.read()), 3, "the server never writes the events log")

    def test_malformed_label_is_400_and_writes_nothing(self) -> None:
        self.seed()
        self.assertEqual(self.call("POST", "/label", json.dumps(self.GOOD).encode())[0], 400, "no content-type")
        self.assertEqual(self.call("POST", "/label", json.dumps(self.GOOD).encode(),
                                   {"Content-Type": "text/plain"})[0], 400)
        for raw in (b"{not json", b"", b"[1]", b"\xff\xfe"):
            self.assertEqual(self.call("POST", "/label", raw, JSON)[0], 400, raw)
        bad = [dict(self.GOOD, label="x"), dict(self.GOOD, event_ts=""), dict(self.GOOD, session_id=7),
               dict(self.GOOD, event_ts=TS % 5), dict(self.GOOD, session_id="other"),
               dict(self.GOOD, question="drifting"), dict(self.GOOD, question="needs_owner", event_ts=log.read()[2]["ts"])]
        del bad[0]["label"]
        for fields in bad:
            status, body = self.post_label(**fields)
            self.assertEqual(status, 400, fields)
            self.assertIn("error", body)
        self.assertFalse(os.path.exists(log.labels_path()))
        self.assertEqual(len(log.read()), 3)


if __name__ == "__main__":
    unittest.main()
