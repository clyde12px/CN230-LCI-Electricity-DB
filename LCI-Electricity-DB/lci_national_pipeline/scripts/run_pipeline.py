from __future__ import annotations
import argparse, csv, json, re, sys, subprocess, tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"
STAGING = OUT / "staging"
MAPPED = OUT / "mapped"
REPORTS = OUT / "reports"
CONFIG = json.loads((ROOT / "config" / "pipeline.json").read_text(encoding="utf-8"))
COMMON = ["source","dataset","source_file","source_row_number","reference_year","reference_month","source_label","flow_name","direction","amount","unit","data_role","compartment","loadable","validation_only","notes","raw_value"]


def write_csv(path, rows, fields=COMMON):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def read_csv(path):
    for enc in ("utf-8-sig", "cp874", "utf-8"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode CSV: {path.name}")


def dec(value):
    if value is None or str(value).strip() == "": return None
    return Decimal(str(value).strip().replace(",", ""))


def extract_dede(spec):
    p = RAW / spec["file"]
    rows = read_csv(p)
    out=[]
    for i,r in enumerate(rows, start=2):
        out.append({"source":"DEDE","dataset":spec["dataset"],"source_file":p.name,"source_row_number":i,
          "reference_year":r["reference_year"],"reference_month":"","source_label":r["flow_name_en"],
          "flow_name":"","direction":"","amount":r.get("amount",""),"unit":r.get("unit",""),
          "data_role":r.get("data_role",""),"compartment":"","loadable":"","validation_only":"",
          "notes":r.get("notes",""),"raw_value":r.get("raw_value","")})
    return out


def extract_eppo(spec):
    p=RAW/spec["file"]; rows=read_csv(p); out=[]
    for i,r in enumerate(rows,start=2):
        out.append({"source":"EPPO","dataset":spec["dataset"],"source_file":p.name,"source_row_number":i,
          "reference_year":r["Year"],"reference_month":r["Month"],"source_label":r["Fuel Type"],
          "flow_name":"","direction":"","amount":r["Quantity"],"unit":r["UNIT"],"data_role":"ELECTRICITY_OUTPUT",
          "compartment":"","loadable":"false","validation_only":"false","notes":"Monthly electricity generation; existing EPPO DB dataset, verify only.","raw_value":r["Quantity"]})
    return out


def extract_emissions(spec):
    try:
        import pandas as pd
    except ImportError as e: raise RuntimeError("Install dependencies first: pip install -r requirements.txt") from e
    p=RAW/spec["file"]
    try:
        df=pd.read_excel(p,sheet_name=spec.get("sheet",0),header=None,engine="xlrd")
    except ImportError:
        # Fallback for environments without xlrd: convert legacy .xls to .xlsx via LibreOffice.
        converted=OUT/"converted"; converted.mkdir(parents=True,exist_ok=True)
        cmd=["libreoffice","--headless","--convert-to","xlsx","--outdir",str(converted),str(p)]
        subprocess.run(cmd,check=True,capture_output=True,text=True)
        xlsx=converted/(p.stem+".xlsx")
        df=pd.read_excel(xlsx,sheet_name=spec.get("sheet",0),header=None,engine="openpyxl")
    out=[]; started=False
    # The source sheet has a main annual data table followed by a separate GROWTH RATE (%) table.
    # Only the first table is extracted; growth-rate rows are not emissions quantities.
    for idx,row in df.iterrows():
        year=row.iloc[0] if len(row)>0 else None
        if isinstance(year,str) and "GROWTH" in year.upper(): break
        try: y=int(float(year))
        except (TypeError,ValueError): continue
        if not (spec["year_min"] <= y <= spec["year_max"]): continue
        started=True
        labels=["Oil","Coal/Lignite","Natural Gas","Total"]
        for col,label in enumerate(labels,start=1):
            value=row.iloc[col] if len(row)>col else None
            if value is None or str(value)=="nan": continue
            out.append({"source":"EPPO","dataset":spec["dataset"],"source_file":p.name,"source_row_number":int(idx)+1,
              "reference_year":y,"reference_month":"","source_label":label,"flow_name":"","direction":"",
              "amount":str(value),"unit":spec["unit"],"data_role":"CO2_EMISSION","compartment":"air",
              "loadable":"","validation_only":"","notes":"Annual CO2 emission reported by EPPO; total is validation-only.","raw_value":str(value)})
    if not started: raise ValueError("Could not locate annual CO2 table in workbook")
    return out


def extract_all():
    results={}
    for key,spec in CONFIG["sources"].items():
        fmt=spec["format"]
        rows=extract_dede(spec) if fmt=="csv_dede" else extract_eppo(spec) if fmt=="csv_monthly_electricity" else extract_emissions(spec)
        results[key]=rows
        write_csv(STAGING/f"{key.lower()}_extracted.csv",rows)
    return results


def stage_and_map(extracted):
    mapped={}
    for key,rows in extracted.items():
        out=[]
        lookup=CONFIG["mapping"].get(key,{})
        for r in rows:
            label=r["source_label"]
            m=lookup.get(label)
            if key=="DEDE_FUEL":
                # Keep DEDE electricity outputs for reconciliation only; do not import alongside EPPO outputs.
                if r["data_role"]=="ELECTRICITY_OUTPUT":
                    r.update({"flow_name":"DEDE electricity output - reconciliation only","direction":"OUTPUT","loadable":"false","validation_only":"true"})
                elif m:
                    has_amount = r.get("amount") not in (None, "")
                    r.update({"flow_name":m["flow_name"],"direction":m["direction"],"loadable":str(has_amount).lower(),"validation_only":str(not has_amount).lower()})
            elif key=="EPPO_ELECTRICITY" and m:
                r.update({"flow_name":m["flow_name"],"direction":m["direction"],"loadable":"false","validation_only":"true"})
            elif key=="EPPO_CO2" and m:
                r.update({"flow_name":m["flow_name"],"direction":m["direction"],"loadable":str(m.get("loadable",False)).lower(),"validation_only":str(m.get("validation_only",False)).lower(),"compartment":m.get("compartment","")})
            else:
                r.update({"flow_name":"UNMAPPED","direction":"","loadable":"false","validation_only":"false"})
            out.append(r)
        mapped[key]=out
        write_csv(MAPPED/f"{key.lower()}_mapped.csv",out)
    return mapped


def validate(mapped):
    errors=[]; warnings=[]; stats={}
    expected={k:v.get("expected_rows") for k,v in CONFIG["sources"].items()}
    for key,rows in mapped.items():
        stats[key]={"rows":len(rows),"years":sorted({int(r["reference_year"]) for r in rows if str(r["reference_year"]).strip()}),"missing_amounts":0,"mapped":0}
        if expected.get(key) is not None and len(rows)!=expected[key]: errors.append(f"{key}: expected {expected[key]} rows, found {len(rows)}")
        seen=set()
        for r in rows:
            try: year=int(r["reference_year"])
            except Exception: errors.append(f"{key} row {r['source_row_number']}: invalid year {r['reference_year']!r}"); continue
            spec=CONFIG["sources"][key]
            if not spec["year_min"]<=year<=spec["year_max"]: errors.append(f"{key} row {r['source_row_number']}: year out of range {year}")
            if r["amount"] in (None,""):
                stats[key]["missing_amounts"]+=1
                warnings.append(f"{key} row {r['source_row_number']}: missing amount retained as missing, not zero")
            else:
                try:
                    n=dec(r["amount"])
                    if n is None: raise InvalidOperation()
                    if n<0: errors.append(f"{key} row {r['source_row_number']}: negative amount {n}")
                except Exception: errors.append(f"{key} row {r['source_row_number']}: non-numeric amount {r['amount']!r}")
            if r.get("flow_name") and r["flow_name"]!="UNMAPPED": stats[key]["mapped"]+=1
            if r.get("flow_name")=="UNMAPPED": errors.append(f"{key} row {r['source_row_number']}: unmapped label {r['source_label']}")
            month=str(r.get("reference_month","")).strip()
            if key=="EPPO_ELECTRICITY" and not month: errors.append(f"{key} row {r['source_row_number']}: missing month")
            k=(key,year,month,r["source_label"])
            if k in seen: errors.append(f"{key}: duplicate key {k}")
            seen.add(k)
        if key=="EPPO_CO2":
            years={int(r["reference_year"]) for r in rows}
            if len(years)!=spec["expected_data_years"]: errors.append(f"EPPO_CO2: expected {spec['expected_data_years']} annual years, found {len(years)}")
    return errors,warnings,stats


def reconcile(mapped):
    rows=[]; by_year=defaultdict(lambda:defaultdict(Decimal))
    # EPPO monthly electricity to annual sums
    for r in mapped["EPPO_ELECTRICITY"]:
        y=int(r["reference_year"]); label=r["source_label"]
        by_year[y][label]+=dec(r["amount"]) or Decimal(0)
    dede=defaultdict(dict)
    for r in mapped["DEDE_FUEL"]:
        if r["data_role"]=="ELECTRICITY_OUTPUT" and r["amount"] not in (None,""):
            dede[int(r["reference_year"])][r["source_label"]]=dec(r["amount"])
    for y, vals in sorted(dede.items()):
        if "Small Hydro" in vals and "Large Hydro" in vals and "Hydro Electricity" in by_year[y]:
            de=vals["Small Hydro"]+vals["Large Hydro"]; ep=by_year[y]["Hydro Electricity"]
            rows.append({"check":"DEDE Hydro (Small+Large) vs EPPO Hydro Electricity","year":y,"de_de_value":str(de),"eppo_value":str(ep),"difference_de_de_minus_eppo":str(de-ep),"status":"WARNING_DIFFERENT_SOURCE_SCOPE","note":"Retain both source values; difference is not forced to zero."})
    emission=defaultdict(dict)
    for r in mapped["EPPO_CO2"]: emission[int(r["reference_year"])][r["source_label"]]=dec(r["amount"])
    for y,v in sorted(emission.items()):
        components=[v.get("Oil"),v.get("Coal/Lignite"),v.get("Natural Gas")]
        if all(x is not None for x in components) and v.get("Total") is not None:
            sm=sum(components,Decimal(0)); total=v["Total"]; diff=sm-total
            rows.append({"check":"EPPO CO2 component sum vs published Total","year":y,"de_de_value":str(sm),"eppo_value":str(total),"difference_de_de_minus_eppo":str(diff),"status":"PASS" if abs(diff)<=Decimal("0.02") else "WARNING_ROUNDING_OR_SOURCE_DIFFERENCE","note":"Total is validation-only and is not loaded as an additional exchange."})
    path=REPORTS/"reconciliation.csv"
    fields=["check","year","de_de_value","eppo_value","difference_de_de_minus_eppo","status","note"]
    write_csv(path,rows,fields)
    return rows


def main():
    ap=argparse.ArgumentParser(description="Config-driven National LCI data pipeline")
    ap.parse_args()
    for p in (STAGING,MAPPED,REPORTS): p.mkdir(parents=True,exist_ok=True)
    extracted=extract_all()
    mapped=stage_and_map(extracted)
    errors,warnings,stats=validate(mapped)
    rec=reconcile(mapped)
    report={"run_at":datetime.now().isoformat(timespec="seconds"),"project":CONFIG["project_name"],"stats":stats,"fatal_errors":errors,"warnings_count":len(warnings),"warnings_sample":warnings[:30],"reconciliation_rows":len(rec),"quality_gate":"FAILED" if errors else "PASSED_WITH_WARNINGS" if warnings else "PASSED"}
    (REPORTS/"quality_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    with (REPORTS/"validation_warnings.txt").open("w",encoding="utf-8") as f:
        f.write("\n".join(warnings) if warnings else "No warnings.")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors: sys.exit(2)

if __name__=="__main__": main()
