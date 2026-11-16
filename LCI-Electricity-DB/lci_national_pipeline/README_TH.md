# Thailand Electricity Generation – National LCI Pipeline (MVP)

ชุดนี้เป็น Pipeline แบบ config-driven สำหรับข้อมูล National 3 ชุด โดยแยกจากสคริปต์เดิมของ EGAT/EPPO เพื่อป้องกันการกระทบฐานข้อมูลเดิม

## ขอบเขตข้อมูล

1. DEDE Table 42: ปริมาณเชื้อเพลิง/ทรัพยากรในการผลิตไฟฟ้ารายปี 2019–2023 (เก็บหน่วยต้นทาง)
2. EPPO Electricity Generation by Energy Type: ปริมาณไฟฟ้ารายเดือน 1986–2026 (ใช้ตรวจสอบ/สรุปรายปีเท่านั้น เพราะมีในฐานข้อมูลเดิมแล้ว)
3. EPPO Table 9.1-3Y: CO2 emission รายปี 1987–2025 หน่วย 1,000 Tons (แยก Oil, Coal/Lignite, Natural Gas; Total ใช้ตรวจสอบเท่านั้น)

ข้อมูล EGAT เดิมไม่ถูกแก้ไข และไม่รวมกับ National input เพื่อป้องกัน double counting

## วิธีติดตั้ง (Windows CMD)

```cmd
cd C:\Users\Hello\Documents\LCI-Electricity-DB
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r national_pipeline\requirements.txt
```

แตก ZIP แล้วคัดลอกโฟลเดอร์ `national_pipeline` ไปไว้ใน project folder แล้วรัน:

```cmd
py national_pipeline\scripts\run_pipeline.py
```

ถ้าติดตั้ง `xlrd` ไม่ได้ แต่เครื่องมี LibreOffice สามารถใช้ตัวแปลง `.xls` เป็น `.xlsx` สำรองได้

ผลลัพธ์อยู่ใน `national_pipeline\outputs\`:
- `staging`: ข้อมูลที่อ่านจากต้นทางและจัดรูปแบบกลาง
- `mapped`: ข้อมูลที่ map เป็น canonical flow และ direction
- `reports\quality_report.json`: ผลตรวจสอบหลัก
- `reports\validation_warnings.txt`: คำเตือน เช่น ค่าที่ต้นทางไม่รายงาน
- `reports\reconciliation.csv`: เปรียบเทียบ Hydro DEDE/EPPO และผลรวม CO2 components กับ Total

## หลักการสำคัญ

- ค่าว่างหรือ `-` จากต้นทางจะไม่ถูกแปลงเป็น 0
- เก็บ `source_file`, `source_row_number`, ปี/เดือน, ชื่อเดิม, หน่วยเดิม และหมายเหตุ
- ไม่รวมยอดรวมเชื้อเพลิงกับรายการย่อย
- ไม่โหลด DEDE electricity output ซ้ำกับ EPPO electricity output
- ไม่โหลด CO2 Total พร้อมกับองค์ประกอบทั้งสาม
- การเปรียบเทียบ DEDE/EPPO เป็น reconciliation เท่านั้น ไม่บังคับให้ตัวเลขเท่ากัน
- ไม่อ้างว่าเป็นข้อมูลรายโรงไฟฟ้าหรือความสัมพันธ์เชิงสาเหตุระดับโรงไฟฟ้า

## สถานะการ Load เข้า PostgreSQL

เวอร์ชันนี้ทำ Extract → Staging → Mapping → Validation → Reconciliation → Quality Gate และสร้าง mapped files ที่พร้อมใช้สำหรับขั้น Load แต่ **ยังไม่สั่ง INSERT/UPDATE ฐานข้อมูลอัตโนมัติ** เพราะต้องตรวจ schema/technology_id/source metadata และข้อกำหนด flow_type ในฐานข้อมูลจริงก่อน เพื่อไม่เสี่ยงสร้าง process/exchange ผิดประเภทหรือกระทบข้อมูล EGAT/EPPO เดิม

ก่อนทำ Load ให้รัน SQL แบบอ่านอย่างเดียวจาก project root:

```cmd
docker compose exec -T postgres psql -U lci_admin -d lci_electricity < national_pipeline\sql\preflight.sql
```

ส่งผลลัพธ์กลับมาตรวจ จากนั้นจึงสร้าง Load adapter ให้ตรงกับ schema จริง
