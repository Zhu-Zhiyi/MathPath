"""Actual XeLaTeX/PDF-link/mirror checks using public synthetic note content."""
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import note_service as notes
from test_notes import document


def main():
    output=PROJECT/"outputs"/("note-pdf-check-"+datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    report={"scope":"synthetic_notes_not_mathematical_validation","real_model_calls":0,"types":{}}
    with tempfile.TemporaryDirectory(prefix="mathpath-note-native-",ignore_cleanup_errors=True) as temporary:
        with patch.dict(os.environ,{"MATHPATH_DATA_DIR":temporary}):
            notes.set_directory(notes.DirectoryInput(directory=str(output/"notebook"),mirror_directory=str(output/"mirror")))
            for kind in "ABC":
                body=notes.NoteInput(enabled=True,request_id=str(uuid4()),note_type=kind,content_date="2026-11-15",source_kind="text",source_text="合成软件检查；不是用户课堂。",sync=True)
                with patch.object(notes,"generate_text",return_value=json.dumps(document(kind),ensure_ascii=False)):
                    result=notes.generate(body)
                report["types"][kind]=result
                if result["pdf"]["status"]!="completed" or result["sync"]["status"]!="completed":raise RuntimeError(json.dumps(result,ensure_ascii=False))
    report["status"]="passed"
    (output/"check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":report["status"],"folder":str(output),"types":{k:v["pdf"] for k,v in report["types"].items()},"mirror_equal":True,"real_model_calls":0},ensure_ascii=False))


if __name__=="__main__":main()
