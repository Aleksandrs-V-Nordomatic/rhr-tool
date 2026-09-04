#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The download, and the two failures a four-day trial against the live register produced.

Both were found by running, not by reading. One lost fifteen procurements out of seventy-nine
and the other lost one, and neither raised anything a reader would have recognised as the
cause: the first reported "path too long" about a file nobody asked for by name, and the
second reported a connection reset as a tender that could not be fetched.
"""

import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_fetch
import ee_page
import net


def zip_bytes(members=(("a.txt", "hello"),)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, payload in members:
            z.writestr(name, payload)
    return buf.getvalue()


class Register(object):
    """Hands out an address, then answers it however the test decided."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.addresses = 0
        self.downloads = 0
        self.opener = None

    def package(self, pid):
        self.addresses += 1
        return "%s/filetransfer/client/shared/package/%d" % (ee_page.BASE, self.addresses)

    def open_url(self, request, **kw):
        self.downloads += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer, {"content-type": "application/zip"}


class ARetryAsksForANewAddress(unittest.TestCase):
    """The address works once, so a retry that reuses it is a retry that cannot succeed.

    Worse than that: a second request with a spent address is not an error, it is an answer
    saying the procurement has no documents. A retry loop around the URL would therefore turn
    one hiccup into a confident, wrong statement about a tender.
    """

    def setUp(self):
        self.original_package = ee_page.package
        self.original_open = net.open_url
        self.original_session = ee_page._SESSION[0]
        self.original_sleep = ee_fetch.time.sleep
        ee_fetch.time.sleep = lambda _s: None
        ee_page._SESSION[0] = type("S", (), {"opener": None})()
        self.addCleanup(self.restore)

    def restore(self):
        ee_page.package = self.original_package
        net.open_url = self.original_open
        ee_page._SESSION[0] = self.original_session
        ee_fetch.time.sleep = self.original_sleep

    def wire(self, answers):
        register = Register(answers)
        ee_page.package = register.package
        net.open_url = register.open_url
        return register

    def test_an_ordinary_reset_is_survived(self):
        # The failure that cost a tender: one connection reset, no retry, procurement lost.
        register = self.wire([ConnectionResetError(10054, "reset"), zip_bytes()])
        self.assertTrue(ee_fetch.archive("1").startswith(b"PK"))
        self.assertEqual(register.downloads, 2)

    def test_and_each_attempt_takes_a_fresh_address(self):
        register = self.wire([ConnectionResetError(10054, "reset"), zip_bytes()])
        ee_fetch.archive("1")
        self.assertEqual(register.addresses, 2,
                         "a second attempt reused the address, which is spent")

    def test_a_register_that_says_there_is_nothing_is_not_retried(self):
        # `Refused` is the register answering, not the transport failing. Asking again is
        # rude and cannot change the answer.
        def refuse(pid):
            raise ee_page.Refused("nothing to download")
        ee_page.package = refuse
        net.open_url = lambda *a, **k: (b"", {})
        with self.assertRaises(ee_page.Refused):
            ee_fetch.archive("1")

    def test_giving_up_says_how_many_attempts_and_why(self):
        register = self.wire([ConnectionResetError(10054, "reset")] * net.TRIES)
        with self.assertRaises(net.Unreachable) as raised:
            ee_fetch.archive("1")
        self.assertIn("attempt", str(raised.exception))
        self.assertEqual(register.downloads, net.TRIES)


class AnAnswerThatIsNotAnArchive(unittest.TestCase):
    """A 200 proves nothing; the magic number does.

    A service under load answers with an HTML error page as readily as with a file, and both
    arrive as bytes under a 200.
    """

    def setUp(self):
        self.original_package = ee_page.package
        self.original_open = net.open_url
        self.original_session = ee_page._SESSION[0]
        self.original_sleep = ee_fetch.time.sleep
        ee_fetch.time.sleep = lambda _s: None
        ee_page._SESSION[0] = type("S", (), {"opener": None})()
        self.addCleanup(self.restore)

    def restore(self):
        ee_page.package = self.original_package
        net.open_url = self.original_open
        ee_page._SESSION[0] = self.original_session
        ee_fetch.time.sleep = self.original_sleep

    def test_html_under_a_200_is_not_taken_for_a_tender(self):
        register = Register([b"<html>error</html>"] * net.TRIES)
        ee_page.package = register.package
        net.open_url = register.open_url
        with self.assertRaises(Exception) as raised:
            ee_fetch.archive("1")
        self.assertNotIsInstance(raised.exception, zipfile.BadZipFile)


if __name__ == "__main__":
    unittest.main()
