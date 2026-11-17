from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..services.auth import current_user,admin
from ..controllers.archive import ArchiveController as C
router=APIRouter()
@router.get('/archive')
def archive(db=Depends(db_session),u=Depends(current_user)):return C.overview(db)
@router.post('/migrations')
def create(db=Depends(db_session),u=Depends(admin)):return C.create(db,u)
@router.post('/migrations/{id}/advance')
def advance(id:int,db=Depends(db_session),u=Depends(admin)):return C.advance(db,u,id)
