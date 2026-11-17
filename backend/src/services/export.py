from fastapi import HTTPException
from fastapi.responses import Response
from ..models.note import Note
from .runs import get_run
from . import archive
def csv_response(result,filename):
    return Response(archive.csv_bytes(result),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})
def run_csv(db,id):
    r=get_run(db,id)
    if r.state!='completed':raise HTTPException(409,'结果尚未完成')
    return archive.serve(db,'run',r.id)
def note_csv(db,id):
    n=db.get(Note,id)
    if not n:raise HTTPException(404,'未找到说明')
    if n.state!='approved':raise HTTPException(403,'仅批准后的业务说明可导出')
    return archive.serve(db,'note',n.id)
