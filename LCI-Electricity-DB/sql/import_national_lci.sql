\set ON_ERROR_STOP on

BEGIN;
SET search_path TO lci_electricity, public;

-- 1. สร้าง Source ใหม่สำหรับ EPPO CO2 (Idempotent)
INSERT INTO lci_source (source_name, source_type, publisher, source_year, reference_url, notes)
SELECT
    'CO2 Emission in Power Generation by Energy Type - EPPO Table 9.1-3Y',
    'Government Energy Statistics',
    'สำนักงานนโยบายและแผนพลังงาน (EPPO)',
    2025,
    NULL,
    'EPPO Table 9.1-3Y: CO2 Emission in Power Generation by Energy Type (1987-2025). Unit: 1,000 Tons. Components imported: Oil, Coal/Lignite, Natural Gas (Total excluded).'
WHERE NOT EXISTS (
    SELECT 1 FROM lci_source
    WHERE source_name = 'CO2 Emission in Power Generation by Energy Type - EPPO Table 9.1-3Y'
);

-- 2. สร้าง 4 Flows ใหม่ (Idempotent)
INSERT INTO lci_flow (flow_name, category_id, flow_type, compartment, default_unit_id, description)
VALUES
    ('HSD', 1, 'PRODUCT', NULL, 3, 'High-Speed Diesel (HSD) fuel input for electricity generation (kept distinct from Diesel Oil).'),
    ('CO2 - Oil', 2, 'ELEMENTARY', 'air', 2, 'Carbon dioxide (CO2) emission to air from oil-fired power generation (EPPO Table 9.1-3Y).'),
    ('CO2 - Coal/Lignite', 2, 'ELEMENTARY', 'air', 2, 'Carbon dioxide (CO2) emission to air from coal and lignite power generation (EPPO Table 9.1-3Y).'),
    ('CO2 - Natural Gas', 2, 'ELEMENTARY', 'air', 2, 'Carbon dioxide (CO2) emission to air from natural gas power generation (EPPO Table 9.1-3Y).')
ON CONFLICT (flow_name, flow_type, compartment) DO NOTHING;

-- 3. สร้าง Temporary Staging Tables เพื่ออ่านข้อมูลตรงจาก CSV
CREATE TEMP TABLE tmp_mapped_csv (
    source TEXT,
    dataset TEXT,
    source_file TEXT,
    source_row_number TEXT,
    reference_year INT,
    reference_month INT,
    source_label TEXT,
    flow_name TEXT,
    direction TEXT,
    amount NUMERIC(24,10),
    unit TEXT,
    data_role TEXT,
    compartment TEXT,
    loadable BOOLEAN,
    validation_only BOOLEAN,
    notes TEXT,
    raw_value TEXT
) ON COMMIT DROP;

\copy tmp_mapped_csv FROM 'lci_national_pipeline/outputs/mapped/dede_fuel_mapped.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
\copy tmp_mapped_csv FROM 'lci_national_pipeline/outputs/mapped/eppo_co2_mapped.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

-- 4. ตรวจสอบจำนวนแถวและกติกาความถูกต้องก่อน Insert
DO $$
DECLARE
    v_dede_loadable INT;
    v_eppo_loadable INT;
    v_val_only INT;
BEGIN
    SELECT COUNT(*) INTO v_dede_loadable
    FROM tmp_mapped_csv
    WHERE source_file ILIKE '%DEDE%' AND loadable = TRUE AND validation_only = FALSE;

    SELECT COUNT(*) INTO v_eppo_loadable
    FROM tmp_mapped_csv
    WHERE source_file NOT ILIKE '%DEDE%' AND loadable = TRUE AND validation_only = FALSE;

    SELECT COUNT(*) INTO v_val_only
    FROM tmp_mapped_csv
    WHERE validation_only = TRUE;

    IF v_dede_loadable <> 62 THEN
        RAISE EXCEPTION 'DEDE loadable count mismatch: got %, expected 62', v_dede_loadable;
    END IF;
    IF v_eppo_loadable <> 117 THEN
        RAISE EXCEPTION 'EPPO CO2 loadable count mismatch: got %, expected 117', v_eppo_loadable;
    END IF;
    IF v_val_only <> 72 THEN
        RAISE EXCEPTION 'Validation-only count mismatch: got %, expected 72', v_val_only;
    END IF;
    IF EXISTS (SELECT 1 FROM tmp_mapped_csv WHERE loadable = TRUE AND (amount IS NULL OR amount < 0 OR reference_month IS NOT NULL)) THEN
        RAISE EXCEPTION 'Invalid amount or non-null reference_month in loadable rows';
    END IF;
    IF EXISTS (SELECT 1 FROM tmp_mapped_csv WHERE loadable = TRUE AND TRIM(flow_name) IN ('Diesel Oil', 'Total', 'CO2 - Total', 'CO2 Total')) THEN
        RAISE EXCEPTION 'Forbidden flow detected in loadable rows';
    END IF;
END $$;

-- 5. สร้าง 44 Annual Processes (5 DEDE + 39 EPPO CO2)
INSERT INTO lci_process (process_name, technology_id, reference_year, geography_id, source_id, domain, description, reference_month)
SELECT DISTINCT
    'DEDE National Fuel Consumption - ' || reference_year,
    3,
    reference_year,
    1,
    3,
    'Electricity Generation',
    'Annual national aggregated fuel consumption for electricity generation (' || reference_year || '), DEDE Energy Balance of Thailand 2023 Table 42. Original source units preserved; not plant-specific and not normalized per kWh.',
    NULL
FROM tmp_mapped_csv
WHERE loadable = TRUE AND UPPER(TRIM(direction)) = 'INPUT'
  AND NOT EXISTS (
      SELECT 1 FROM lci_process p
      WHERE p.source_id = 3 AND p.technology_id = 3 AND p.geography_id = 1
        AND p.reference_year = tmp_mapped_csv.reference_year AND p.reference_month IS NULL
  )
ORDER BY reference_year;

INSERT INTO lci_process (process_name, technology_id, reference_year, geography_id, source_id, domain, description, reference_month)
SELECT DISTINCT
    'EPPO CO2 Emission in Power Generation - ' || reference_year,
    2,
    reference_year,
    1,
    (SELECT source_id FROM lci_source WHERE source_name = 'CO2 Emission in Power Generation by Energy Type - EPPO Table 9.1-3Y'),
    'Electricity Generation',
    'Annual national CO2 emissions from power generation by energy type (' || reference_year || '), EPPO Table 9.1-3Y (Unit: 1,000 Tons). National aggregated data; not plant-specific and not normalized per kWh.',
    NULL
FROM tmp_mapped_csv
WHERE loadable = TRUE AND UPPER(TRIM(direction)) = 'OUTPUT'
  AND NOT EXISTS (
      SELECT 1 FROM lci_process p
      JOIN lci_source s ON p.source_id = s.source_id
      WHERE s.source_name = 'CO2 Emission in Power Generation by Energy Type - EPPO Table 9.1-3Y'
        AND p.technology_id = 2 AND p.geography_id = 1
        AND p.reference_year = tmp_mapped_csv.reference_year AND p.reference_month IS NULL
  )
ORDER BY reference_year;

-- 6. Insert 179 Exchanges พร้อม Data Lineage
INSERT INTO lci_exchange (process_id, flow_id, direction, amount, unit_id, is_reference_flow, source_id, notes)
SELECT
    CASE
        WHEN UPPER(TRIM(t.direction)) = 'INPUT' THEN (
            SELECT p.process_id FROM lci_process p
            WHERE p.source_id = 3 AND p.technology_id = 3 AND p.geography_id = 1
              AND p.reference_year = t.reference_year AND p.reference_month IS NULL
        )
        ELSE (
            SELECT p.process_id FROM lci_process p
            JOIN lci_source s ON p.source_id = s.source_id
            WHERE s.source_name = 'CO2 Emission in Power Generation by Energy Type - EPPO Table 9.1-3Y'
              AND p.technology_id = 2 AND p.geography_id = 1
              AND p.reference_year = t.reference_year AND p.reference_month IS NULL
        )
    END AS process_id,
    CASE
        WHEN UPPER(TRIM(t.direction)) = 'INPUT' THEN (
            SELECT f.flow_id FROM lci_flow f
            WHERE f.flow_name = TRIM(t.flow_name) AND f.flow_type = 'PRODUCT' AND f.compartment IS NULL
        )
        ELSE (
            SELECT f.flow_id FROM lci_flow f
            WHERE f.flow_name = TRIM(t.flow_name) AND f.flow_type = 'ELEMENTARY' AND f.compartment = 'air'
        )
    END AS flow_id,
    UPPER(TRIM(t.direction)) AS direction,
    t.amount,
    CASE LOWER(TRIM(t.unit))
        WHEN 'mmscf' THEN 1
        WHEN '1,000 tons' THEN 2
        WHEN '1000 tons' THEN 2
        WHEN 'million litres' THEN 3
        WHEN 'gwh' THEN 4
        WHEN 'kg' THEN 5
        WHEN 'g' THEN 6
        WHEN 'm3' THEN 7
        WHEN 'mj' THEN 8
        WHEN 'gj' THEN 9
    END AS unit_id,
    FALSE AS is_reference_flow,
    CASE
        WHEN UPPER(TRIM(t.direction)) = 'INPUT' THEN 3
        ELSE (SELECT source_id FROM lci_source WHERE source_name = 'CO2 Emission in Power Generation by Energy Type - EPPO Table 9.1-3Y')
    END AS source_id,
    'source_file=' || TRIM(t.source_file) || ' | source_row=' || TRIM(t.source_row_number) || ' | source_label=' || TRIM(t.source_label)
        || CASE WHEN COALESCE(TRIM(t.notes), '') <> '' THEN ' | note=' || TRIM(t.notes) ELSE '' END AS notes
FROM tmp_mapped_csv t
WHERE t.loadable = TRUE
ORDER BY t.direction, t.reference_year, t.source_row_number::INT;

-- 7. ตรวจสอบยอดรวมสุดท้ายก่อน Commit (ต้องได้ Processes = 1,016 และ Exchanges = 5,473)
DO $$
DECLARE
    v_proc_cnt BIGINT;
    v_exch_cnt BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_proc_cnt FROM lci_process;
    SELECT COUNT(*) INTO v_exch_cnt FROM lci_exchange;

    IF v_proc_cnt <> 1016 THEN
        RAISE EXCEPTION 'Final lci_process count mismatch: got %, expected 1016', v_proc_cnt;
    END IF;
    IF v_exch_cnt <> 5473 THEN
        RAISE EXCEPTION 'Final lci_exchange count mismatch: got %, expected 5473', v_exch_cnt;
    END IF;
END $$;

SELECT 'lci_source' AS table_name, COUNT(*) AS row_count FROM lci_source
UNION ALL SELECT 'lci_flow', COUNT(*) FROM lci_flow
UNION ALL SELECT 'lci_process', COUNT(*) FROM lci_process
UNION ALL SELECT 'lci_exchange', COUNT(*) FROM lci_exchange;

COMMIT;