#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What `--check` is allowed to refuse, and what it must let through.

This check runs FIRST in the night, before the register is touched, and it exists to catch the
two failures that would otherwise be discovered after a day of archives had already been
downloaded: a credential that has expired, and a drive or root that does not answer.

It used to ask whether the COUNTRY folder existed, which is a different question with the same
shape. For a country delivered for months a missing folder really does mean the root is wrong.
For a country nobody has delivered yet it means "first run" — and the check refused, blaming a
setting that was correct, at the first step of the first night. The folder is not a precondition
of anything: Graph creates intermediate folders for an upload addressed by path.
"""

import io
import os
import sys
import unittest
import contextlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deliver_ee
import deliver_graph


class Drive(object):
    """Answers `item_at` from a set of paths the test says exist."""

    def __init__(self, present):
        self.present = set(present)
        self.asked = []

    def item_at(self, drive, path, tok):
        self.asked.append(path)
        if path in self.present:
            return {"folder": {"childCount": 7}}
        return None


class Check(unittest.TestCase):
    ROOT = "Shared/project/work"

    def setUp(self):
        self.original_token = deliver_graph.graph_token
        self.original_item = deliver_graph.item_at
        deliver_graph.graph_token = lambda: "a-token"
        self.addCleanup(setattr, deliver_graph, "graph_token", self.original_token)
        self.addCleanup(setattr, deliver_graph, "item_at", self.original_item)
        for name, value in (("GRAPH_DRIVE_ID", "drive-1"),
                            ("GRAPH_DEST_ROOT", self.ROOT),
                            ("EIS_COUNTRY", "EE")):
            self.addCleanup(os.environ.pop, name, None)
            os.environ[name] = value

    def run_check(self, present):
        drive = Drive(present)
        deliver_graph.item_at = drive.item_at
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = deliver_ee.main(["--check", "--country", "EE"])
        return code, out.getvalue() + err.getvalue(), drive

    def test_a_country_nobody_has_delivered_yet_passes(self):
        """The case that would have cost the first night of every new country."""
        code, said, _ = self.run_check([self.ROOT])
        self.assertEqual(code, 0, said)

    def test_and_it_says_so_rather_than_letting_a_count_imply_it(self):
        _, said, _ = self.run_check([self.ROOT])
        self.assertIn("first delivery", said)

    def test_a_country_already_on_the_drive_still_reports_what_is_there(self):
        code, said, _ = self.run_check([self.ROOT, self.ROOT + "/EE"])
        self.assertEqual(code, 0, said)
        self.assertIn("7 item(s)", said)

    def test_a_root_that_is_not_there_still_fails(self):
        """The failure this check exists for, and it is about the root, not the country."""
        code, said, _ = self.run_check([])
        self.assertEqual(code, 2)
        self.assertIn("GRAPH_DEST_ROOT", said)

    def test_the_root_is_what_gets_asked_about_first(self):
        # Asking the country folder first would make a first run's answer depend on a
        # question that cannot fail informatively.
        _, _, drive = self.run_check([self.ROOT])
        self.assertEqual(drive.asked[0], self.ROOT)

    def test_a_credential_that_will_not_get_a_token_fails_before_the_drive(self):
        def refuse():
            raise RuntimeError("invalid client secret")
        deliver_graph.graph_token = refuse
        drive = Drive([self.ROOT])
        deliver_graph.item_at = drive.item_at
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = deliver_ee.main(["--check", "--country", "EE"])
        self.assertEqual(code, 2)
        self.assertIn("client secret", err.getvalue())
        self.assertEqual(drive.asked, [], "the drive was asked after the token failed")


if __name__ == "__main__":
    unittest.main()
