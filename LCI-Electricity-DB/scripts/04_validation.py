
import csv
import subprocess
import tempfile
from pathlib import Path
from decimal import Decimal, InvalidOperation
from collections import Counter

TEMP_DIR = Path(tempfile.gettempdir()) / "LCI-Electricity-DB"
MAPPED_DIR = TEMP_DIR / "mapped"
LOG_DIR = TEMP_DIR / "logs"

EXPECTED_COUNTS = {
    "EPPO": 3381,
    "EGAT": 1913,
}

EXPECTED_DIRECTIONS = {
    "EPPO": "OUTPUT",
    "EGAT": "INPUT",
}

EXPECTED_UNITS = {
    "Natural Gas": "MMSCF",
    "Lignite": "1,000 Tons",
    "Diesel Oil": "Million Litres",
    "Fuel Oil": "Million Litres",
    "Palm Oil": "Million Litres",
    "Electricity - Hydro": "GWh",
    "Electricity - Fuel Oil": "GWh",
    "Electricity - Coal & Lignite": "GWh",
    "Electricity - Natural Gas": "GWh",
    "Electricity - Diesel": "GWh",
    "Electricity - Imported": "GWh",
    "Electricity - Renewable Energy": "GWh",
}

REQUIRED_COLUMNS = [
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


def get_database_flows():
    sql = """
    SELECT f.flow_name, u.unit_symbol
    FROM lci_electricity.lci_flow f
    JOIN lci_electricity.unit u
      ON f.default_unit_id = u.unit_id
    ORDER BY f.flow_name;
    """

    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T",
            "postgres", "psql",
            "-U", "lci_admin",
            "-d", "lci_electricity",
            "-A", "-t", "-F", "|",
            "-c", sql,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    flows = {}

    for line in result.stdout.splitlines():
        if "|" in line:
            name, unit = line.strip().split("|", 1)
            flows[name] = unit

    return flows


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    errors = []
    warnings = []
    total_records = 0
    all_keys = set()
    source_counts = Counter()
    flow_counts = Counter()

    print("CONNECTING TO DATABASE...")

    try:
        database_flows = get_database_flows()
        print(f"Database flows found: {len(database_flows)}")
    except Exception as error:
        print("DATABASE CHECK FAILED:", error)
        return

    for source in ["EPPO", "EGAT"]:
        file_path = MAPPED_DIR / f"{source.lower()}_mapped.csv"

        if not file_path.exists():
            errors.append(f"{source}: mapped file not found")
            continue

        with open(file_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            missing_columns = [
                col for col in REQUIRED_COLUMNS
                if col not in (reader.fieldnames or [])
            ]

            if missing_columns:
                errors.append(
                    f"{source}: missing columns {missing_columns}"
                )
                continue

            records = list(reader)

        print(f"\nSOURCE: {source}")
        print(f"Records found: {len(records)}")

        if len(records) != EXPECTED_COUNTS[source]:
            errors.append(
                f"{source}: expected {EXPECTED_COUNTS[source]}, "
                f"found {len(records)}"
            )

        for row in records:
            total_records += 1
            source_counts[source] += 1

            row_number = row["source_row_number"]
            flow = row["flow_name"]

            try:
                year = int(row["year"])
                month = int(row["month_number"])
                quantity = Decimal(row["quantity"])

                if not 1900 <= year <= 2200:
                    raise ValueError("Invalid year")

                if not 1 <= month <= 12:
                    raise ValueError("Invalid month")

                if not quantity.is_finite() or quantity < 0:
                    raise ValueError("Invalid quantity")

            except (ValueError, InvalidOperation) as error:
                errors.append(
                    f"{source} row {row_number}: {error}"
                )
                continue

            if row["source"] != source:
                errors.append(
                    f"{source} row {row_number}: source mismatch"
                )

            if row["direction"] != EXPECTED_DIRECTIONS[source]:
                errors.append(
                    f"{source} row {row_number}: wrong direction"
                )

            if flow not in EXPECTED_UNITS:
                errors.append(
                    f"{source} row {row_number}: unknown flow {flow}"
                )
                continue

            expected_unit = EXPECTED_UNITS[flow]

            if row["unit"] != expected_unit:
                errors.append(
                    f"{source} row {row_number}: "
                    f"expected {expected_unit}, found {row['unit']}"
                )

            if flow not in database_flows:
                errors.append(
                    f"{source} row {row_number}: "
                    f"flow not found in database: {flow}"
                )
            elif database_flows[flow] != row["unit"]:
                errors.append(
                    f"{source} row {row_number}: "
                    f"database unit mismatch for {flow}"
                )

            key = (
                source,
                year,
                month,
                flow,
                row["direction"],
            )

            if key in all_keys:
                errors.append(
                    f"{source} row {row_number}: duplicate record"
                )

            all_keys.add(key)
            flow_counts[(source, flow)] += 1

    print("\n--- VALIDATION SUMMARY ---")
    print(f"Total records: {total_records}")

    for source in ["EPPO", "EGAT"]:
        print(f"{source}: {source_counts[source]}")

    print(f"Duplicate keys: {total_records - len(all_keys)}")
    print(f"Errors: {len(errors)}")

    report = [
        "LCI ELECTRICITY - VALIDATION REPORT",
        f"Total records: {total_records}",
        f"EPPO: {source_counts['EPPO']}",
        f"EGAT: {source_counts['EGAT']}",
        f"Errors: {len(errors)}",
    ]

    if errors:
        report.append("\nVALIDATION FAILED")
        report.extend(errors)
        print("\nVALIDATION FAILED")

        for error in errors[:20]:
            print("ERROR:", error)
    else:
        report.append("\nVALIDATION PASSED")
        print("\nVALIDATION PASSED")

    report_file = LOG_DIR / "04_validation_report.txt"
    report_file.write_text("\n".join(report), encoding="utf-8")

    print(f"\nReport saved: {report_file}")


if __name__ == "__main__":
    main()
