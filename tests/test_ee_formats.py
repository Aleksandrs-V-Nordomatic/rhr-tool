#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two container formats this country adds, and why each is decided by its bytes.

Both are ZIP files. Neither can be told apart from the other, or from a Word document, by
looking at the name a buyer typed — and getting either one wrong is silent: an open-format
spreadsheet handed to the archive path yields `content.xml` instead of a price table, and a
signed container handed to the converter yields nothing at all.
"""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import normalize


def container(members, name="x.bin"):
    path = os.path.join(tempfile.mkdtemp(), name)
    with zipfile.ZipFile(path, "w") as z:
        for member, payload in members:
            z.writestr(member, payload)
    return path


class OpenFormatDocumentsGoToTheConverter(unittest.TestCase):
    """An .ods is a ZIP with none of the OOXML members, so without this it is UNPACKED.

    A reader is then handed `content.xml` and `styles.xml` instead of the buyer's price
    table, every count still adds up, and nothing reports a failure.
    """

    def test_a_spreadsheet_is_recognised_by_the_media_type_it_stores(self):
        path = container([("mimetype", "application/vnd.oasis.opendocument.spreadsheet"),
                          ("content.xml", "<x/>")])
        self.assertEqual(normalize.sniff(path), ".ods")

    def test_and_so_are_the_other_two(self):
        for media, extension in (
                ("application/vnd.oasis.opendocument.text", ".odt"),
                ("application/vnd.oasis.opendocument.presentation", ".odp")):
            with self.subTest(media=media):
                path = container([("mimetype", media), ("content.xml", "<x/>")])
                self.assertEqual(normalize.sniff(path), extension)

    def test_the_extension_a_buyer_typed_does_not_decide(self):
        # Contracting authorities send a spreadsheet named .doc often enough that the whole
        # sniffing layer exists because of it.
        path = container([("mimetype", "application/vnd.oasis.opendocument.spreadsheet"),
                          ("content.xml", "<x/>")], name="hinnatabel.doc")
        self.assertEqual(normalize.sniff(path), ".ods")

    def test_each_one_has_somewhere_to_go(self):
        # Recognising a format and being able to read it are different claims, and a sniffer
        # that names a format with no reader behind it just moves the silence one step along.
        for extension in (".ods", ".odt", ".odp"):
            self.assertIn(extension, normalize.LEGACY)


class SignedContainersStayArchives(unittest.TestCase):
    """A signed container is a folder with signatures in it, and has to be opened as one.

    It carries a `mimetype` member exactly as an OpenDocument file does, so a rule that fired
    on the member's presence rather than on its value would send every signed tender to the
    converter, which would produce nothing and report a conversion failure for a file that is
    perfectly readable.
    """

    def test_it_is_read_as_an_archive_not_as_a_document(self):
        path = container([("mimetype", "application/vnd.etsi.asic-e+zip"),
                          ("META-INF/signatures0.xml", "<x/>"),
                          ("Tehniline kirjeldus.pdf", "%PDF-1.4")])
        self.assertEqual(normalize.sniff(path), ".zip")
        self.assertIn(".zip", normalize.ARCHIVES)

    def test_the_containers_own_plumbing_is_named_rather_than_read(self):
        # Listed as packaging, never dropped: "nothing vanishes" is the claim the extractor
        # keeps, and signature XML is not a document.
        self.assertTrue(normalize.is_container_part("mimetype"))
        self.assertTrue(normalize.is_container_part("META-INF/signatures0.xml"))
        self.assertFalse(normalize.is_container_part("Tehniline kirjeldus.pdf"))


class TheFormatsAlreadyRead(unittest.TestCase):
    """Guarding the boundary the two additions above sit next to."""

    def test_ooxml_is_still_told_apart_from_a_plain_archive(self):
        self.assertEqual(normalize.sniff(container([("word/document.xml", "<x/>")])), ".docx")
        self.assertEqual(normalize.sniff(container([("xl/workbook.xml", "<x/>")])), ".xlsx")
        self.assertEqual(normalize.sniff(container([("ppt/presentation.xml", "<x/>")])),
                         ".pptx")

    def test_a_zip_with_nothing_recognisable_in_it_is_a_zip(self):
        self.assertEqual(normalize.sniff(container([("a.txt", "hello")])), ".zip")


if __name__ == "__main__":
    unittest.main()
