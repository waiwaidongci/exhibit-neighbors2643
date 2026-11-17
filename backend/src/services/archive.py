import csv,io,hashlib,logging
from pathlib import Path
from datetime import datetime,timezone,timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from fastapi.responses import Response
from ..config.settings import ARTIFACT_DIR
from ..models.run import Run
from ..models.note import Note
from ..models.archive import ArchiveItem,ArchivePointer,DownloadLease,Migration,MigrationFile
from ..utils.serialization import row,now
from .audit import log
ARCHIVE_ROOT=ARTIFACT_DIR/'archive'
QUARANTINE_DIR=ARCHIVE_ROOT/'quarantine'
PROTECTED_NAMES={'heartbeat'}
LEASE_TTL_SECONDS=600
def gen_dir(generation):return ARCHIVE_ROOT/f'gen-{generation}'
def fingerprint(data):return hashlib.sha256(data).hexdigest()
def csv_bytes(result):
    # 唯一权威字节口径：只序列化冻结结果，绝不重新计算评分
    buf=io.StringIO();fields=result['columns'];w=csv.DictWriter(buf,fieldnames=fields);w.writeheader()
    for r in result['rows']:w.writerow({k:r.get(k,'') for k in fields})
    return ('﻿'+buf.getvalue()).encode('utf-8')
def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp');tmp.write_bytes(data);tmp.replace(path)
def frozen_result(db,kind,ref_id):
    # 原件=数据库中的冻结结果；迁移与修复只允许读取它，禁止调用算法重算
    if kind=='run':
        r=db.get(Run,ref_id);return r.result if r and r.state=='completed' else None
    n=db.get(Note,ref_id);return n.frozen_result if n and n.state=='approved' else None
def active_pointer(db):
    p=db.get(ArchivePointer,1)
    if p:return p
    gen_dir(0).mkdir(parents=True,exist_ok=True)
    p=ArchivePointer(id=1,active_dir=str(gen_dir(0)),generation=0,updated_at=now())
    db.add(p)
    try:db.commit()
    except IntegrityError:db.rollback();p=db.get(ArchivePointer,1)
    return p
def isolate(path):
    # 损坏件隔离：移出服务目录留待核查，不再作为原件提供
    path=Path(path);QUARANTINE_DIR.mkdir(parents=True,exist_ok=True)
    target=QUARANTINE_DIR/(datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'-'+path.name)
    path.replace(target);return target
def quarantine_item(db,item,reason,actor='system'):
    item.state='quarantined';item.blocked_reason=reason[:400];item.updated_at=now()
    log(db,actor,'archive.quarantined',item.filename,reason[:400]);db.commit()
def authentic_bytes(db,item,actor='system'):
    # 读取当前文件并核对登记指纹；损坏或缺失时隔离坏件、按冻结结果重新生成原件字节
    path=Path(item.directory)/item.filename
    try:data=path.read_bytes()
    except OSError:data=None
    if data is not None and fingerprint(data)==item.sha256:return data
    if data is not None:isolate(path)
    result=frozen_result(db,item.kind,item.ref_id)
    if result is None:
        quarantine_item(db,item,'冻结结果缺失，无法核验原件',actor)
        raise HTTPException(409,'留档件已隔离：冻结结果缺失，无法核验原件')
    canonical=csv_bytes(result)
    if fingerprint(canonical)!=item.sha256:
        quarantine_item(db,item,'冻结结果与登记指纹不一致，拒绝以重算内容冒充原件',actor)
        raise HTTPException(409,'留档件已隔离：冻结结果与登记指纹不一致')
    atomic_write(path,canonical)
    item.repairs+=1;item.updated_at=now()
    log(db,actor,'archive.repaired',item.filename,'原文件损坏或缺失，已隔离并按冻结结果重新生成');db.commit()
    return canonical
def register_item(db,kind,ref_id,filename,actor='system'):
    # 幂等登记：已登记件直接沿用并核验；未登记件按冻结结果生成字节与指纹
    item=db.scalar(select(ArchiveItem).where(ArchiveItem.kind==kind,ArchiveItem.ref_id==ref_id))
    if item:
        if item.state=='ready':
            try:authentic_bytes(db,item,actor)
            except HTTPException:pass
        return item
    result=frozen_result(db,kind,ref_id)
    pointer=active_pointer(db)
    if result is None:
        item=ArchiveItem(kind=kind,ref_id=ref_id,filename=filename,sha256='0'*64,bytes=0,state='quarantined',blocked_reason='冻结结果缺失，无法生成原件',directory=pointer.active_dir,generation=pointer.generation,created_at=now(),updated_at=now())
        db.add(item);db.commit();log(db,actor,'archive.quarantined',filename,'冻结结果缺失');db.commit();return item
    canonical=csv_bytes(result)
    item=ArchiveItem(kind=kind,ref_id=ref_id,filename=filename,sha256=fingerprint(canonical),bytes=len(canonical),state='ready',directory=pointer.active_dir,generation=pointer.generation,created_at=now(),updated_at=now())
    db.add(item)
    try:db.commit()
    except IntegrityError:
        db.rollback();return db.scalar(select(ArchiveItem).where(ArchiveItem.kind==kind,ArchiveItem.ref_id==ref_id))
    atomic_write(Path(item.directory)/item.filename,canonical)
    log(db,actor,'archive.registered',filename,'指纹 '+item.sha256[:12]);db.commit()
    return item
def register_run(db,run,actor='worker'):return register_item(db,'run',run.id,f'run-{run.id}.csv',actor)
def register_note(db,note,actor='system'):return register_item(db,'note',note.id,f'approved-{note.id}.csv',actor)
def reconcile(db):
    # 启动对账：为全部已完成任务与已批准快照补齐登记，已登记件沿用不重登
    active_pointer(db)
    for r in db.scalars(select(Run).where(Run.state=='completed')):register_run(db,r)
    for n in db.scalars(select(Note).where(Note.state=='approved')):register_note(db,n)
def item_for(db,kind,ref_id):return db.scalar(select(ArchiveItem).where(ArchiveItem.kind==kind,ArchiveItem.ref_id==ref_id))
def open_lease(db,item):
    # 下载绑定开始时的完整版本：租约记录当时所在目录与代次
    lease=DownloadLease(item_id=item.id,generation=item.generation,path=str(Path(item.directory)/item.filename),started_at=now())
    db.add(lease);db.commit();return lease
def close_lease(db,lease):
    lease.finished_at=now();db.commit()
def open_leases(db,paths=None):
    cutoff=(datetime.now(timezone.utc)-timedelta(seconds=LEASE_TTL_SECONDS)).isoformat()
    q=select(DownloadLease).where(DownloadLease.finished_at.is_(None),DownloadLease.started_at>=cutoff)
    leases=list(db.scalars(q))
    if paths is not None:leases=[x for x in leases if x.path in paths]
    return leases
def serve(db,kind,ref_id):
    item=item_for(db,kind,ref_id)
    if not item:item=register_item(db,kind,ref_id)
    if item.state=='quarantined':raise HTTPException(409,'留档件已隔离：'+item.blocked_reason)
    lease=open_lease(db,item)
    try:
        data=authentic_bytes(db,item)
        return Response(data,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+item.filename+'"'})
    finally:
        close_lease(db,lease)
def overview(db):
    pointer=active_pointer(db)
    items=[row(x) for x in db.scalars(select(ArchiveItem).order_by(ArchiveItem.id))]
    migrations=[row(x) for x in db.scalars(select(Migration).order_by(Migration.generation.desc()))]
    files=[row(x) for x in db.scalars(select(MigrationFile).order_by(MigrationFile.id))]
    return {'pointer':{'active_dir':pointer.active_dir,'generation':pointer.generation},'items':items,'migrations':migrations,'files':files,'open_leases':len(open_leases(db))}
