from __future__ import annotations

import datetime as dt

import pytest

from app.importers.degiro_csv import UnknownFormat, classify, parse_date, parse_export, parse_number
from app.importers.store import check_duplicates, save_export
from app.models import AccountEntry, Product, Transaction
from tests.conftest import ISIN_NL, ISIN_US, make_account_csv, make_transactions_csv


@pytest.mark.parametrize("text,expected", [
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("-12,50", -12.5), ("12.50", 12.5),
    ("1000", 1000.0), ("", None), (None, None), ("abc", None), ("1 234,5", 1234.5),
])
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_parse_date():
    assert parse_date("31-12-2025") == dt.date(2025, 12, 31)
    assert parse_date("2025-12-31") == dt.date(2025, 12, 31)
    assert parse_date("not a date") is None


@pytest.mark.parametrize("text,kind", [
    ("Dividend", "dividend"), ("Dividendbelasting", "dividend_tax"), ("Dividend Tax", "dividend_tax"),
    ("Valuta Debitering", "fx"), ("DEGIRO Transactiekosten en/of kosten van derden", "fee"),
    ("iDEAL storting", "cash"), ("Koop 10 ACME@100 EUR", "trade"), ("Iets heel onbekends", "other"),
])
def test_classify(text, kind):
    assert classify(text) == kind


def test_transactions_dutch_headers_with_amount_then_currency():
    parsed = parse_export(make_transactions_csv())
    assert parsed.kind == "transactions"
    assert len(parsed.transactions) == 4
    first = sorted(parsed.transactions, key=lambda t: t.date)[0]
    assert first.isin == ISIN_NL
    assert first.quantity == 10
    assert first.price == 100.0
    assert first.price_currency == "EUR"
    assert first.total_eur == -1002.0
    assert first.fees_eur == 2.0


def test_english_headers_and_semicolons():
    raw = (
        "Date;Time;Product;ISIN;Reference;Venue;Quantity;Price;;Local value;;Value;;Exchange rate;"
        "Transaction and/or third;;Total;;Order ID\n"
        f"10-01-2024;10:00;ACME;{ISIN_NL};EAM;XAMS;3;10,00;EUR;-30,00;EUR;-30,00;EUR;;-1,00;EUR;-31,00;EUR;x\n"
    ).encode()
    parsed = parse_export(raw)
    assert parsed.transactions[0].quantity == 3
    assert parsed.transactions[0].total_eur == -31.0


def test_bom_and_windows_encoding():
    assert parse_export(b"\xef\xbb\xbf" + make_transactions_csv()).kind == "transactions"
    latin = "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n" \
            '01-01-2025,09:00,01-01-2025,Caf\xe9,,Storting,,EUR,"1,00",EUR,"1,00",\n'
    assert parse_export(latin.encode("cp1252")).entries[0].product == "Café"


def test_account_has_currency_before_amount():
    parsed = parse_export(make_account_csv())
    assert parsed.kind == "account"
    dividend = next(e for e in parsed.entries if e.kind == "dividend" and e.isin == ISIN_NL)
    assert dividend.currency == "EUR"
    assert dividend.amount == 25.0
    assert [e.description for e in parsed.unrecognised] == ["Iets heel onbekends"]


def test_rejects_other_files():
    with pytest.raises(UnknownFormat):
        parse_export(b"a,b,c\n1,2,3\n")
    with pytest.raises(UnknownFormat):
        parse_export(b"")


def test_bad_rows_are_reported_not_saved():
    raw = make_transactions_csv() + b"geen-datum,10:00,X,NL0000000001,EAM,XAMS,1,1,EUR,1,EUR,1,EUR,,0,EUR,1,EUR,o\n"
    raw += b"10-01-2024,10:00,X,KAPOT,EAM,XAMS,1,1,EUR,1,EUR,1,EUR,,0,EUR,1,EUR,o\n"
    parsed = parse_export(raw)
    assert len(parsed.transactions) == 4
    assert {b.reason for b in parsed.bad_rows} == {"ongeldige datum", "ongeldige ISIN"}


def test_reimport_adds_no_duplicates(session):
    parsed = parse_export(make_transactions_csv())
    assert save_export(session, parsed) == 4
    session.commit()
    check = check_duplicates(session, parse_export(make_transactions_csv()))
    assert (check.new, check.duplicates) == (0, 4)
    assert save_export(session, parse_export(make_transactions_csv())) == 0
    assert session.query(Transaction).count() == 4


def test_overlapping_export_only_adds_new_rows(session):
    save_export(session, parse_export(make_account_csv()))
    extra = make_account_csv() + b'06-06-2025,09:00,06-06-2025,,,iDEAL storting,,EUR,"5,00",EUR,"1,00",\n'
    assert save_export(session, parse_export(extra)) == 1
    assert session.query(AccountEntry).count() == 8


def test_identical_rows_in_one_file_are_both_kept(session):
    lines = make_transactions_csv().decode().splitlines(keepends=True)
    raw = (lines[0] + lines[1] + lines[1]).encode()
    assert save_export(session, parse_export(raw)) == 2


def test_import_creates_products(session):
    save_export(session, parse_export(make_transactions_csv()))
    assert session.get(Product, ISIN_US).name == "US CORP"
    assert session.get(Product, ISIN_NL).exchange == "EAM"
