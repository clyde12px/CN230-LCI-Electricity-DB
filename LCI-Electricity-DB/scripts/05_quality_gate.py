
import csv
import io
import subprocess
import tempfile
from pathlib import Path
from decimal import Decimal, InvalidOperation
from collections import Counter

PROJECT_DIR = Path(__file__).resolve().parent.parent
MAPPED_DIR = Path(tempfile.gettempdir()) / "LCI-Electricity-DB" / "mapped"
LOG_DIR = Path(tempfile.gettempdir()) / "LCI-Electricity-DB" / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)

MAPPED_FILES = {
    "EGAT": MAPPED_DIR / "egat_mapped.csv",
    "EPPO": MAPPED_DIR / "eppo_mapped.csv",
}

SOURCE_IDS = {
    "EGAT": "1",
    "EPPO": "2",
}

errors = []
checked = Counter()


def load_mapped_records():
    records = []

    for source, file_path in MAPPED_FILES.items():
        print(f"\nREADING MAPPED: {source}")

        if not file_path.exists():
            errors.append(f"Missing mapped file: {file_path}")
            continue

        with file_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                row["source"] = row["source"].strip().upper()
                records.append(row)

        print(f"Records: {sum(1 for r in records if r['source'] == source)}")

    return records


def load_database_records():
    query = """
    COPY (
        SELECT
            CASE p.source_id
                WHEN 1 THEN 'EGAT'
                WHEN 2 THEN 'EPPO'
            END AS source,
            p.reference_year AS year,
            p.reference_month AS month_number,
            f.flow_name,
            e.direction,
            e.amount,
            u.unit_symbol,
            p.source_id AS process_source_id,
            e.source_id AS exchange_source_id
        FROM lci_electricity.lci_exchange e
        JOIN lci_electricity.lci_process p
            ON e.process_id = p.process_id
        JOIN lci_electricity.lci_flow f
            ON e.flow_id = f.flow_id
        JOIN lci_electricity.unit u
            ON e.unit_id = u.unit_id
        WHERE p.source_id IN (1, 2)
        ORDER BY p.source_id, p.reference_year,
                 p.reference_month, f.flow_name
    ) TO STDOUT WITH CSV HEADER
    """

    command = [
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
        "-U", "lci_admin",
        "-d", "lci_electricity",
        "-c", query,
    ]

    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return list(csv.DictReader(io.StringIO(result.stdout)))


def make_key(row):
    return (
        row["source"].strip().upper(),
        int(row["year"]),
        int(row["month_number"]),
        row["flow_name"].strip(),
        row["direction"].strip().upper(),
    )


def run_quality_gate():
    print("====================================")
    print("LCI ELECTRICITY - QUALITY GATE")
    print("====================================")

    mapped = load_mapped_records()
    database = load_database_records()

    print("\nDATABASE RECORDS:", len(database))
    print("MAPPED RECORDS:", len(mapped))

    mapped_index = {}
    database_index = {}

    # Check duplicate keys in mapped data
    for row in mapped:
        try:
            key = make_key(row)

            if key in mapped_index:
                errors.append(f"Duplicate MAPPED key: {key}")
            else:
                mapped_index[key] = row

        except (ValueError, KeyError) as exc:
            errors.append(f"Invalid MAPPED record: {exc}")

    # Check duplicate keys in database
    for row in database:
        try:
            key = make_key(row)

            if key in database_index:
                errors.append(f"Duplicate DATABASE key: {key}")
            else:
                database_index[key] = row

        except (ValueError, KeyError) as exc:
            errors.append(f"Invalid DATABASE record: {exc}")

    # Compare each mapped record with database
    for key, mapped_row in mapped_index.items():
        checked[key[0]] += 1

        db_row = database_index.get(key)

        if db_row is None:
            errors.append(f"Missing in DATABASE: {key}")
            continue

        try:
            mapped_amount = Decimal(mapped_row["quantity"])
            db_amount = Decimal(db_row["amount"])

            if not mapped_amount.is_finite() or not db_amount.is_finite():
                errors.append(f"Invalid amount: {key}")
            elif mapped_amount != db_amount:
                errors.append(
                    f"Amount mismatch: {key} "
                    f"MAPPED={mapped_amount}, DATABASE={db_amount}"
                )

        except (InvalidOperation, KeyError) as exc:
            errors.append(f"Amount check failed: {key} - {exc}")

        mapped_unit = mapped_row["unit"].strip()
        db_unit = db_row["unit_symbol"].strip()

        if mapped_unit != db_unit:
            errors.append(
                f"Unit mismatch: {key} "
                f"MAPPED={mapped_unit}, DATABASE={db_unit}"
            )

        expected_source_id = SOURCE_IDS.get(key[0])

        if db_row["process_source_id"] != expected_source_id:
            errors.append(f"Process source mismatch: {key}")

        if db_row["exchange_source_id"] != expected_source_id:
            errors.append(f"Exchange source mismatch: {key}")

    # Find database records not present in mapped data
    for key in database_index:
        if key not in mapped_index:
            errors.append(f"Extra record in DATABASE: {key}")

    # Summary
    summary = [
        "LCI ELECTRICITY - QUALITY GATE REPORT",
        "======================================",
        f"Mapped records: {len(mapped)}",
        f"Database records: {len(database)}",
        f"EGAT checked: {checked['EGAT']}",
        f"EPPO checked: {checked['EPPO']}",
        f"Mapped unique keys: {len(mapped_index)}",
        f"Database unique keys: {len(database_index)}",
        f"Errors: {len(errors)}",
        "",
    ]

    if errors:
        summary.append("QUALITY GATE FAILED")
        summary.append("")
        summary.extend(errors)
    else:
        summary.append("QUALITY GATE PASSED")
        summary.append(
            "All mapped records match the existing database."
        )
        summary.append(
            "No database records were inserted, updated, or deleted."
        )

    report = "\n".join(summary)

    print("\n" + report)

    report_path = LOG_DIR / "05_quality_gate_report.txt"
    report_path.write_text(report, encoding="utf-8")

    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    try:
        run_quality_gate()
    except Exception as exc:
        print("\nQUALITY GATE ERROR:", exc)
        raise
