"""Generate a deterministic, deliberately messy customer dataset for demos and benchmarks.

    uv run scripts/make_sample_data.py --rows 1000 --out customers.csv
    uv run --with openpyxl scripts/make_sample_data.py --rows 1000 --out customers.xlsx
    uv run scripts/make_sample_data.py --rows 10000000 --out customers_10m.csv

The mess is the point: missing and placeholder emails, several phone and date formats,
inconsistent country spellings, and PII buried in free text give every transformation
something real to match, and something it must leave alone.
"""

import argparse
import csv
import random

HEADER = ["id", "name", "email", "phone", "country", "signup_date", "notes"]

FIRST = ["John", "Jane", "Alice", "Wei", "Priya", "Omar", "Sofia", "Liam", "Yuki", "Amara"]
LAST = ["Doe", "Smith", "Brown", "Chen", "Patel", "Haddad", "Rossi", "Murphy", "Tanaka", "Okafor"]
DOMAINS = ["example.com", "domain.com", "website.org", "mail.co.uk", "corp.io"]
COUNTRIES = ["USA", "U.S.", "United States", "us", "UK", "United Kingdom", "Great Britain",
             "India", "IN", "Australia", "AUS", "Germany", "Deutschland", ""]
NOTES = ["Prefers contact by phone.", "VIP customer.", "Requested invoice copy.", "",
         "Follow up next quarter.", "No issues reported."]


def _email(rng, first, last):
    roll = rng.random()
    if roll < 0.05:
        return ""
    if roll < 0.10:
        return "N/A"
    sep = rng.choice([".", "_", ""])
    address = f"{first}{sep}{last}{rng.randint(1, 99)}@{rng.choice(DOMAINS)}"
    return address.upper() if roll < 0.15 else address.lower()


def _phone(rng):
    a, b, c = rng.randint(200, 999), rng.randint(100, 999), rng.randint(1000, 9999)
    return rng.choice([f"+1 ({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}{b}{c}", f"+44 20 7{b} {c}", ""])


def _date(rng):
    y, m, d = rng.randint(2019, 2025), rng.randint(1, 12), rng.randint(1, 28)
    month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]
    return rng.choice([f"{y}-{m:02d}-{d:02d}", f"{m:02d}/{d:02d}/{y}", f"{d} {month} {y}"])


def rows(count, seed=42):
    rng = random.Random(seed)
    for i in range(1, count + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        notes = rng.choice(NOTES)
        if rng.random() < 0.3:  # PII hidden in free text
            contact = _email(rng, last, first)
            if "@" not in contact:
                contact = _phone(rng) or "on file"
            notes += f" Alt contact: {contact}"
        yield [i, f"{first} {last}", _email(rng, first, last), _phone(rng),
               rng.choice(COUNTRIES), _date(rng), notes.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--out", required=True, help="output path ending in .csv or .xlsx")
    args = parser.parse_args()

    if args.out.endswith(".xlsx"):
        from openpyxl import Workbook

        book = Workbook(write_only=True)
        sheet = book.create_sheet("customers")
        sheet.append(HEADER)
        for row in rows(args.rows):
            sheet.append(row)
        book.save(args.out)
    else:
        with open(args.out, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)
            writer.writerows(rows(args.rows))
    print(f"wrote {args.rows} rows to {args.out}")


if __name__ == "__main__":
    main()
