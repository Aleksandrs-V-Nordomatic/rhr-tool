#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A delivery longer than one token's life still finishes.

On 12 Nov 2026 a month's catch-up spent 65 minutes uploading and then got a 401 on every
request, because the token fetched at the start of the step had expired. These tests hold the
two things that stop that: the token renews itself on a clock, and a 401 asks for a fresh token
once before it fails the run.
"""

import email.message
import io
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deliver_graph


class Clock(object):
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Issuer(object):
    """Hands out t1, t2, … and counts how often it was asked."""

    def __init__(self):
        self.issued = 0

    def __call__(self):
        self.issued += 1
        return "t%d" % self.issued


def http_error(code):
    return urllib.error.HTTPError("https://graph.example/x", code, "no", email.message.Message(),
                                  io.BytesIO(b""))


class Response(object):
    status = 200

    def __init__(self, body=b"ok"):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Server(object):
    """Answers each request from a script and remembers the Authorization it carried."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    def __call__(self, req, timeout=None):
        self.seen.append(req.get_header("Authorization"))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class TokenTest(unittest.TestCase):

    def test_the_first_token_is_fetched_at_once(self):
        issuer = Issuer()
        deliver_graph.Token(issuer, clock=Clock())
        self.assertEqual(issuer.issued, 1)

    def test_the_same_token_is_used_inside_its_life(self):
        clock, issuer = Clock(), Issuer()
        tok = deliver_graph.Token(issuer, clock=clock)
        clock.now = deliver_graph.Token.RENEW_AFTER - 1
        self.assertEqual(tok.value(), "t1")
        self.assertEqual(issuer.issued, 1)

    def test_a_token_past_its_renewal_time_is_replaced(self):
        clock, issuer = Clock(), Issuer()
        tok = deliver_graph.Token(issuer, clock=clock)
        clock.now = deliver_graph.Token.RENEW_AFTER
        self.assertEqual(tok.value(), "t2")
        clock.now += 60
        self.assertEqual(tok.value(), "t2")

    def test_renewal_comes_before_the_shortest_token_life(self):
        self.assertLess(deliver_graph.Token.RENEW_AFTER, 60 * 60)

    def test_a_bare_string_still_makes_a_header(self):
        self.assertEqual(deliver_graph.bearer("abc"), "Bearer abc")


class UnauthorizedTest(unittest.TestCase):

    def setUp(self):
        self.addCleanup(setattr, deliver_graph.urllib.request, "urlopen",
                        deliver_graph.urllib.request.urlopen)

    def serve(self, answers):
        server = Server(answers)
        deliver_graph.urllib.request.urlopen = server
        return server

    def test_a_read_that_gets_401_retries_with_a_new_token(self):
        server = self.serve([http_error(401), Response(b"body")])
        tok = deliver_graph.Token(Issuer(), clock=Clock())
        self.assertEqual(deliver_graph.get("https://graph.example/x", tok), b"body")
        self.assertEqual(server.seen, ["Bearer t1", "Bearer t2"])

    def test_an_upload_that_gets_401_retries_with_a_new_token(self):
        server = self.serve([http_error(401), Response()])
        tok = deliver_graph.Token(Issuer(), clock=Clock())
        self.assertEqual(deliver_graph.put("https://graph.example/x", b"d", tok), 200)
        self.assertEqual(server.seen, ["Bearer t1", "Bearer t2"])

    def test_a_second_401_fails_the_run(self):
        self.serve([http_error(401), http_error(401)])
        tok = deliver_graph.Token(Issuer(), clock=Clock())
        with self.assertRaises(SystemExit) as caught:
            deliver_graph.get("https://graph.example/x", tok)
        self.assertIn("401", str(caught.exception))

    def test_a_401_with_a_bare_string_fails_at_once(self):
        server = self.serve([http_error(401)])
        with self.assertRaises(SystemExit):
            deliver_graph.get("https://graph.example/x", "abc")
        self.assertEqual(len(server.seen), 1)


if __name__ == "__main__":
    unittest.main()
