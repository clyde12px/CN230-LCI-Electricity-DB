
import csv
import tempfile
from pathlib import Path

TEMP_DIR = Path(tempfile.gettempdir()) / "LCI-Electricity-DB"
STAGING_DIR = TEMP_DIR / "staging"
MAPPED_DIR = TEMP_DIR / "mapped"

MAPPING = {
    "EGAT": {
        "NATURAL GAS": ("Natural Gas", "INPUT", "MMSCF"),
        "LIGNITE": ("Lignite", "INPUT", "1,000 Tons"),
        "DIESEL OIL": ("Diesel Oil", "INPUT", "Million Litres"),
        "FUEL OIL": ("Fuel Oil", "INPUT", "Million Litres"),
        "PALM OIL": ("Palm Oil", "INPUT", "Million Litres"),
    },
    "EPPO": {
        "Hydro Electricity": ("Electricity - Hydro", "OUTPUT", "GWh"),
        "Fuel Oil": ("Electricity - Fuel Oil", "OUTPUT", "GWh"),
        "Coal & Lignite": ("Electricity - Coal & Lignite", "OUTPUT", "GWh"),
        "Natural Gas": ("Electricity - Natural Gas", "OUTPUT", "GWh"),
        "Diesel": ("Electricity - Diesel", "OUTPUT", "GWh"),
        "Imported": ("Electricity - Imported", "OUTPUT", "GWh"),
        "Renewable Energy": ("Electricity - Renewable Energy", "OUTPUT", "GWh"),
    },
}

OUTPUT_COLUMNS = [
    "source",
    "source_file",
    "source_row_number",
    "year",
    "month_number",
    "month_name",
    "source_fuel_type",
    "flow_name",
    "direction",
    "quantity",
    "unit",
]


def main():
    MAPPED_DIR.mkdir(parents=True, exist_ok=True)

    total_mapped = 0
    total_errors = 0
    mapped_by_source = {}

    for source in ["EPPO", "EGAT"]:
        input_file = STAGING_DIR / f"{source.lower()}_staging.csv"

        if not input_file.exists():
            raise FileNotFoundError(input_file)

        mapped_records = []
        errors = []

        with open(input_file, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                fuel = row["source_fuel_type"]

                rule = MAPPING[source].get(fuel)

                if rule is None:
                    errors.append(
                        f"Row {row['source_row_number']}: "
                        f"Unmapped fuel type: {fuel}"
                    )
                    continue

                flow_name, direction, expected_unit = rule

                if row["unit"] != expected_unit:
                    errors.append(
                        f"Row {row['source_row_number']}: "
                        f"{fuel} expected {expected_unit}, "
                        f"found {row['unit']}"
                    )
                    continue

                mapped_records.append({
                    "source": row["source"],
                    "source_file": row["source_file"],
                    "source_row_number": row["source_row_number"],
                    "year": row["year"],
                    "month_number": row["month_number"],
                    "month_name": row["month_name"],
                    "source_fuel_type": fuel,
                    "flow_name": flow_name,
                    "direction": direction,
                    "quantity": row["quantity"],
                    "unit": row["unit"],
                })

        print(f"\nSOURCE: {source}")
        print(f"Mapped records: {len(mapped_records)}")
        print(f"Mapping errors: {len(errors)}")

        if errors:
            for error in errors[:10]:
                print("ERROR:", error)

        total_errors += len(errors)
        total_mapped += len(mapped_records)
        mapped_by_source[source] = mapped_records

    if total_errors:
        print("\nMAPPING FAILED")
        print("No mapped files were written.")
        return

    for source, records in mapped_by_source.items():
        output_file = MAPPED_DIR / f"{source.lower()}_mapped.csv"

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
            writer.writerows(records)

        print(f"\nCreated: {output_file}")
        print(f"Records written: {len(records)}")

    print("\nMAPPING COMPLETED")
    print(f"Total mapped records: {total_mapped}")


if __name__ == "__main__":
    main()
