-- Read-only schema inspection. Does not modify data.
\echo '=== TABLE DEFINITIONS ==='
\d+ lci_electricity.lci_source
\d+ lci_electricity.lci_process
\d+ lci_electricity.lci_flow
\d+ lci_electricity.lci_exchange
\d+ lci_electricity.technology
\d+ lci_electricity.unit
\echo '=== SOURCES ==='
SELECT source_id, source_name, source_type, publisher, source_year, reference_url FROM lci_electricity.lci_source ORDER BY source_id;
\echo '=== TECHNOLOGIES ==='
SELECT * FROM lci_electricity.technology ORDER BY technology_id;
\echo '=== FLOW CATEGORIES ==='
SELECT * FROM lci_electricity.flow_category ORDER BY category_id;
\echo '=== FLOWS ==='
SELECT flow_id, flow_name, flow_type, compartment, default_unit_id, category_id FROM lci_electricity.lci_flow ORDER BY flow_id;
\echo '=== UNITS ==='
SELECT unit_id, unit_name, unit_symbol, dimension, conversion_factor, is_base_unit FROM lci_electricity.unit ORDER BY unit_id;
\echo '=== PROCESS NULLABILITY / DEFAULTS ==='
SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='lci_electricity' AND table_name='lci_process' ORDER BY ordinal_position;
\echo '=== UNIQUE / CHECK CONSTRAINTS ==='
SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace='lci_electricity'::regnamespace ORDER BY conrelid::regclass::text, conname;
