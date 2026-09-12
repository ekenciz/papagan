import argparse

import pytest

from epub2m4b.cli import parse_chapter_selector


def test_parse_chapter_selector_supports_ranges():
    assert parse_chapter_selector("1,3-5,9") == (1, 3, 4, 5, 9)


def test_parse_chapter_selector_rejects_invalid_range():
    with pytest.raises(argparse.ArgumentTypeError):
        parse_chapter_selector("5-3")


def test_parse_xtts_workers_auto_and_manual():
    from epub2m4b.cli import parse_xtts_workers

    assert parse_xtts_workers("auto") == 0
    assert parse_xtts_workers("otomatik") == 0
    assert parse_xtts_workers("4") == 4


def test_model_license_is_accepted_by_default_and_can_be_disabled():
    from epub2m4b.cli import build_parser

    parser = build_parser()
    default_args = parser.parse_args(["convert", "in.epub", "out.m4b"])
    assert default_args.accept_model_license is True

    rejected_args = parser.parse_args(["convert", "in.epub", "out.m4b", "--no-accept-model-license"])
    assert rejected_args.accept_model_license is False
