
import csv
from decimal import Decimal
from pathlib import Path
from collections import Counter

# Locate project folders based on this script
PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_DIR / "data" / "raw"

FILES = {
    "EPPO": "การผลิตไฟฟ้าแยกตามชนิดเชื้อเพลิง",
    "EGAT": "การใช้เชื้อเพลิงในการผลิตไฟฟ้าของ กฟผ_",
}

EXPECTED_COLUMNS = [
    "Year", "Month", "Fuel Type", "Quantity", "UNIT"
]


def read_csv_file(file_path):
    """Read CSV without modifying the original file."""

    for encoding in ["utf-8-sig", "cp874"]:
        try:
            with open(
                file_path,
                "r",
                encoding=encoding,
                newline=""
            ) as file:
                rows = list(csv.reader(file))

            return rows, encoding

        except UnicodeDecodeError:
            continue

    raise ValueError(f"Cannot decode file: {file_path.name}")


def inspect_file(source_name, file_name):
    file_path = RAW_DIR / file_name

    print("\n" + "=" * 55)
    print(f"SOURCE: {source_name}")
    print(f"FILE: {file_path.name}")

    if not file_path.exists():
        print("ERROR: File not found")
        return

    rows, encoding = read_csv_file(file_path)

    if not rows:
        print("ERROR: Empty file")
        return

    header = [value.strip() for value in rows[0]]

    if header[:5] != EXPECTED_COLUMNS:
        print("ERROR: Unexpected column structure")
        print("Found:", header)
        return

    valid_records = []
    errors = []

    for line_number, row in enumerate(rows[1:], start=2):
        values = [value.strip() for value in row]

        # Ignore empty trailing columns
        extra_values = [v for v in values[5:] if v]
        if extra_values and any(
            v != values[4] for v in extra_values
        ):
            errors.append((line_number, "Unexpected extra data"))
            continue

        if len(values) < 5:
            errors.append((line_number, "Missing columns"))
            continue

        record = dict(zip(EXPECTED_COLUMNS, values[:5]))

        if not all(record.values()):
            errors.append((line_number, "Missing value"))
            continue

        try:
            int(record["Year"])
            quantity = Decimal(record["Quantity"].strip())

            if not quantity.is_finite() or quantity < 0:
                raise ValueError("Invalid quantity")
            
        except ValueError:
            errors.append((line_number, "Invalid number"))
            continue

        valid_records.append(record)

    print(f"Encoding: {encoding}")
    print(f"Total data rows: {len(rows) - 1}")
    print(f"Valid records: {len(valid_records)}")
    print(f"Invalid records: {len(errors)}")

    if valid_records:
        years = [int(r["Year"]) for r in valid_records]
        units = Counter(r["UNIT"] for r in valid_records)
        fuels = Counter(r["Fuel Type"] for r in valid_records)

        print(f"Year range: {min(years)} - {max(years)}")
        print(f"Units: {dict(units)}")
        print(f"Fuel types: {dict(fuels)}")

        print("\nFirst 3 records:")
        for record in valid_records[:3]:
            print(record)

    if errors:
        print("\nFirst 5 errors:")
        for error in errors[:5]:
            print(error)


def main():
    print("LCI ELECTRICITY - EXTRACT CHECK")
    print(f"Project directory: {PROJECT_DIR}")

    for source_name, file_name in FILES.items():
        inspect_file(source_name, file_name)

    print("\nEXTRACT CHECK COMPLETED")


if __name__ == "__main__":
    main()
