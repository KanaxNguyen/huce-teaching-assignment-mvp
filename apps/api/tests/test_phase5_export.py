from openpyxl import Workbook, load_workbook
import pytest
from sqlalchemy import select
from app.db.session import Base, SessionLocal, engine
from app.exporters.excel import export_latest
from app.models.entities import OutputTemplateProfile
from app.optimization.solver import solve
from test_phase3_solver import setup, capability

@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); yield; Base.metadata.drop_all(engine)

def test_template_export_updates_only_lecturer_source_rows(tmp_path):
    source=tmp_path/"source.xlsx"; book=Workbook(); sheet=book.active; sheet.title="S"; sheet.append(["Mã học phần","Mã lớp học","Giảng viên","Phòng"]); sheet.append(["C","L0","old","P"]); book.save(source)
    with SessionLocal() as db:
        s,c,a,b,items=setup(db); capability(db,a,c); run=solve(db,2,False,s.id)
        db.add(OutputTemplateProfile(semester_id=s.id,source_file=str(source),source_sheet="S",header_row=1,mappings={"course_code":{"column_index":1},"class_code":{"column_index":2},"lecturer":{"column_index":3}},missing_fields=[])); db.commit()
        result=export_latest(db,tmp_path/"out",s.id)
        output=load_workbook(result)["S"]
        assert output.max_row==2 and output.cell(2,1).value=="C" and output.cell(2,2).value=="L0" and output.cell(2,4).value=="P"
        assert output.cell(2,3).value=="A"
