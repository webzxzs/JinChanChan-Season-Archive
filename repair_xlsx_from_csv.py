"""无需 Excel 启动的既有工作簿数据更新后备方案。

只更新与 CSV 等行等列的4个既有工作表，保留原来的格式、筛选和冻结窗格；
不改变表结构、不伪造缺失内容。列数/行数不匹配则拒绝覆盖。
"""
import csv
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"金铲铲全赛季研究资料库.xlsx"
SHEETS=("棋子","羁绊与效果","棋盘可能效果","赛季特色")
NS="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XML="http://www.w3.org/XML/1998/namespace"
ET.register_namespace("",NS)

def col(i):
    s=""
    while i:
        i,r=divmod(i-1,26)
        s=chr(65+r)+s
    return s

def apply_sheet(content, rows, numeric):
    root=ET.fromstring(content)
    sheet_data=root.find(f"{{{NS}}}sheetData")
    if sheet_data is None:raise ValueError("缺少sheetData")
    existing=sheet_data.findall(f"{{{NS}}}row")
    if len(existing)!=len(rows):
        raise ValueError(f"工作表行数改变：旧{len(existing)} 新{len(rows)}；拒绝覆盖，需重新创建模板")
    for ri,record in enumerate(rows,1):
        row=existing[ri-1]
        if int(row.attrib.get("r",ri))!=ri:
            raise ValueError("工作簿已有不连续行号")
        current={re.sub(r"\d+","",c.attrib.get("r","")):c for c in row.findall(f"{{{NS}}}c")}
        for ci,value in enumerate(record,1):
            key=col(ci)
            cell=current.get(key)
            if cell is None:
                cell=ET.Element(f"{{{NS}}}c", {"r":key+str(ri)})
                pos=0
                for other in list(row):
                    if other.tag!=f"{{{NS}}}c":continue
                    oldkey=re.sub(r"\d+","",other.attrib.get("r",""))
                    if col_index(oldkey)<ci:pos+=1
                row.insert(pos,cell)
            for old in list(cell):cell.remove(old)
            value=str(value or "")
            if not value:
                cell.attrib.pop("t",None)
                continue
            if ri>1 and ci in numeric and re.fullmatch(r"-?\d+(?:\.\d+)?",value):
                cell.attrib.pop("t",None)
                ET.SubElement(cell,f"{{{NS}}}v").text=value
            else:
                cell.set("t","inlineStr")
                string=ET.SubElement(cell,f"{{{NS}}}is")
                t=ET.SubElement(string,f"{{{NS}}}t")
                if value.startswith(" ") or value.endswith(" "):
                    t.set(f"{{{XML}}}space","preserve")
                t.text=value
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)

def col_index(text):
    n=0
    for c in text:n=n*26+ord(c)-64
    return n

def main():
    if not OUT.exists():raise FileNotFoundError(OUT)
    tables={}
    for name in SHEETS:
        with (ROOT/"tables"/(name+".csv")).open(encoding="utf-8-sig",newline="") as f:
            records=list(csv.reader(f))
        if not records:raise ValueError(name+"空文件")
        tables[name]=records
    numeric={
        "棋子":{5,11,12,13,14,15,16,17},
        "羁绊与效果":set(),"棋盘可能效果":set(),"赛季特色":{6,7}
    }
    updated={}
    with ZipFile(OUT,"r") as book:
        if book.testzip():raise ValueError("已有工作簿ZIP校验失败")
        for i,name in enumerate(SHEETS,1):
            path=f"xl/worksheets/sheet{i}.xml"
            original=book.read(path)
            xml=apply_sheet(original,tables[name],numeric[name])
            updated[path]=xml
            print("已更新",name,len(tables[name])-1,"条",len(tables[name][0]),"列")
        temp=OUT.with_name(OUT.name+".tmp")
        with ZipFile(temp,"w") as out:
            for member in book.infolist():
                payload=updated.get(member.filename)
                out.writestr(member,payload if payload is not None else book.read(member.filename))
    with ZipFile(temp) as check:
        if check.testzip():raise ValueError("生成工作簿ZIP校验失败")
        for i in range(1,5):
            ET.fromstring(check.read(f"xl/worksheets/sheet{i}.xml"))
    temp.replace(OUT)
    print("校验完成",OUT,OUT.stat().st_size)

if __name__=="__main__":main()
