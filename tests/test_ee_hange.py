"""hange.ee's two lists, from pages built to the site's markup, with no network and no drive.

Under test: a private person's request never reaches a record, the fields stop where the site
ends them, the request list pages until it runs out, and a list that failed withdraws nothing.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ee_hange


def notice(ident, title, field="Automaatika", due="26.11.2026"):
    return ('<tr><td class="first"><div class="table-txt flex"><h2><a data-notice-id="%s" '
            'onClick="x" href="javscript:;" class="trigger-modal register-click border-link"\n>\n'
            '  %s\n</a><span class="hasfiles"><img src="/img/icon-clip.svg"></span></h2><p>'
            '<span class="light">Asukoht:</span> Põlvamaa<br><span class="light">Valdkond:</span> '
            '%s<br><span class="light">\n Pakkumisi oodatakse kuni:\n </span>\n %s\n'
            '<span class="about">?</span><br></p></div></td></tr>' % (ident, title, field, due))


def request(ident, title, organiser, due="18.11.2026", added="11.11.2026", offers=2):
    return ('<tr class=""><td class="first"><div class="table-txt flex"><h2>'
            '<a class="border-link" href="https://www.hange.ee/%s/slug/">%s</a></h2><p>'
            '<span class="light">Asukoht:</span>\nHarjumaa, Tallinn.<br>'
            '<span class="light">Hanke etapp:</span>\n Pakkumiste tegemine kuni %s<br/>'
            '<span class="light">Hanke korraldaja:</span>\n\t%s\n</p>'
            '<div class="table-info-mobile"><span class="light">Pakkumisi:</span>'
            '<strong>%d</strong><br/></div></div></td>\n<td>%s</td>\n<td>3p</td></tr>'
            % (ident, title, due, organiser, offers, added))


NOTICES = "<table><tbody>%s%s</tbody></table>" % (
    notice(2143, "Hoone automaatika korraline hooldus"),
    notice(2142, "Pargi valgustuse projekt", field="Projekteerimine", due="18.11.2026"))
PAGE_1 = ("<table>%s%s</table><a href='?filter=all-active&page=2'>2</a>"
          % (request(147012, "Vanniseina paigaldus", "eraisik"),
             request(147010, "Ventilatsiooni hooldus", "ettevõte")))
PAGE_2 = "<table>%s</table>" % request(146900, "Katlamaja automaatika", "omavalitsus")


class Lists(unittest.TestCase):
    def test_a_notice_is_read_whole(self):
        first = ee_hange.notices(NOTICES)[0]
        self.assertEqual(first["key"], "HANGE-NOTICE:2143")
        self.assertEqual(first["title"], "Hoone automaatika korraline hooldus")
        self.assertEqual((first["county"], first["field"], first["deadline"]),
                         ("Põlvamaa", "Automaatika", "2026-11-26"))
        self.assertTrue(first["has_files"])

    def test_a_private_persons_request_is_never_kept(self):
        rows, skipped = ee_hange.requests(PAGE_1)
        self.assertEqual(skipped, 1)
        self.assertEqual([r["organiser"] for r in rows], ["ettevõte"],
                         "the organiser stops where the site ends it, not at the offer count")
        self.assertEqual((rows[0]["deadline"], rows[0]["added"]), ("2026-11-18", "2026-11-11"))
        self.assertNotIn("Vanniseina", repr(rows))


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="ee-hange-")
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def served(self, failing=()):
        def get(url):
            if any(word in url for word in failing):
                raise OSError("no answer")
            if "hanketeated" in url:
                return NOTICES
            return PAGE_1 if url.endswith("page=1") else PAGE_2 if url.endswith("page=2") else ""
        return get

    def test_requests_page_until_the_list_ends(self):
        snap = ee_hange.collect(self.out, "2026-11-11", get=self.served())
        self.assertEqual(snap["sources"]["requests"]["pages"], 2)
        self.assertEqual(snap["sources"]["requests"]["private_skipped"], 1)
        self.assertEqual(sorted(i["key"] for i in snap["items"] if "REQUEST" in i["key"]),
                         ["HANGE-REQUEST:146900", "HANGE-REQUEST:147010"])

    def test_a_list_that_failed_withdraws_nothing(self):
        before = ee_hange.collect(self.out, "2026-11-10", get=self.served())
        now = ee_hange.collect(self.out, "2026-11-11", get=self.served(failing=("hanketeated",)))
        changes = ee_hange.diff(before, now)
        self.assertIn("error", now["sources"]["notices"])
        self.assertEqual(changes["gone"], [])

    def test_the_diff_says_what_moved(self):
        before = ee_hange.collect(self.out, "2026-11-10", get=self.served())
        now = dict(before, date="2026-11-11",
                   items=[dict(i, deadline="2026-12-01") if i["key"] == "HANGE-NOTICE:2143" else i
                          for i in before["items"] if i["key"] != "HANGE-NOTICE:2142"])
        changes = ee_hange.diff(before, now)
        self.assertEqual([g["key"] for g in changes["gone"]], ["HANGE-NOTICE:2142"])
        self.assertEqual(changes["changed"][0]["moved"]["deadline"], ["2026-11-26", "2026-12-01"])


if __name__ == "__main__":
    unittest.main()
