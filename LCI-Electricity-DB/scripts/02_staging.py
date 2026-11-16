
import csv
import tempfile
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
STAGING_DIR = Path(tempfile.gettempdir()) / "LCI-Electricity-DB" / "staging"

FILES = {
    "EPPO": "การผลิตไฟฟ้าแยกตามชนิดเชื้อเพลิง",
    "EGAT": "การใช้เชื้อเพลิงในการผลิตไฟฟ้าของ กฟผ_",
}

MONTHS = {
    "january": 1, "february": 2,
    "march": 3, "april": 4,
    "may": 5, "june": 6,
    "july": 7, "august": 8,
    "september": 9, "october": 10,
    "november": 11, "december": 12,
}

OUTPUT_COLUMNS = [
    "source",
    "source_file",
    "source_row_number",
    "year",
    "month_number",
    "month_name",
    "source_fuel_type",
    "quantity",
    "unit",
]


def read_source(file_path):
    for encoding in ["utf-8-sig", "cp874"]:
        try:
            with open(file_path, encoding=encoding, newline="") as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Cannot decode {file_path.name}")


def prepare_records(source, file_name):
    file_path = RAW_DIR / file_name

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    rows = read_source(file_path)

    if not rows:
        raise ValueError(f"Empty file: {file_name}")

    header = [v.strip() for v in rows[0]]

    expected = ["Year", "Month", "Fuel Type", "Quantity", "UNIT"]

    if header[:5] != expected:
        raise ValueError(f"Unexpected header in {file_name}: {header}")

    records = []
    errors = []

    for row_number, row in enumerate(rows[1:], start=2):
        values = [v.strip() for v in row]

        # Allow empty trailing columns or a repeated unit.
        extra_values = [v for v in values[5:] if v]

        if extra_values and any(v != values[4] for v in extra_values):
            errors.append((row_number, "Unexpected extra data"))
            continue

        if len(values) < 5:
            errors.append((row_number, "Missing columns"))
            continue

        year_text, month_text, fuel, quantity_text, unit = values[:5]

        try:
            year = int(year_text)
            month_number = MONTHS[month_text.lower()]
            quantity = Decimal(quantity_text)

            # Normalize floating-point artifacts from source data
            rounded = quantity.quantize(Decimal("0.000001"))
            if abs(quantity - rounded) <= Decimal("0.000000001"):
                quantity = rounded

            if not quantity.is_finite() or quantity < 0:
                raise ValueError("Quantity must be finite and non-negative")

            if not 1900 <= year <= 2200:
                raise ValueError("Invalid year")

            if not fuel or not unit:
                raise ValueError("Missing fuel type or unit")

        except (ValueError, KeyError, InvalidOperation) as error:
            errors.append((row_number, str(error)))
            continue

        records.append({
            "source": source,
            "source_file": file_name,
            "source_row_number": row_number,
            "year": year,
            "month_number": month_number,
            "month_name": month_text.title(),
            "source_fuel_type": fuel,
            "quantity": str(quantity),
            "unit": unit,
        })

    return records, errors


def main():
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    all_records = []
    total_errors = 0

    for source, file_name in FILES.items():
        records, errors = prepare_records(source, file_name)

        print(f"\nSOURCE: {source}")
        print(f"Valid records: {len(records)}")
        print(f"Invalid records: {len(errors)}")

        if errors:
            print("First 5 errors:", errors[:5])

        all_records.extend(records)
        total_errors += len(errors)

    if total_errors:
        print("\nSTAGING STOPPED: Invalid records found.")
        print("No staging files were written.")
        return

    # Write separate staging files by source.
    for source in FILES:
        source_records = [
            record for record in all_records
            if record["source"] == source
        ]

        output_file = STAGING_DIR / f"{source.lower()}_staging.csv"

        with open(
            output_file,
            "w",
            encoding="utf-8-sig",
            newline=""
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=OUTPUT_COLUMNS
            )
            writer.writeheader()
            writer.writerows(source_records)

        print(f"\nCreated: {output_file}")
        print(f"Records written: {len(source_records)}")

    print("\nSTAGING COMPLETED")
    print(f"Total staged records: {len(all_records)}")


if __name__ == "__main__":
    main()
