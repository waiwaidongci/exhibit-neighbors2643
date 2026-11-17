import logging,secrets
from pathlib import Path
from sqlalchemy import select,update
from fastapi import HTTPException
from ..models.archive import ArchiveItem,Migration,MigrationFile,ArchivePointer
from ..utils.serialization import now
from .audit import log
from . import archive
from .runs import queue
ACTIVE_STATES=('copying','copied','switching','switched','reclaiming','blocked')
RESUMABLE_STATES=('copying','copied','switching','switched','reclaiming','blocked')
PRE_SWITCH_STATES=('copying','copied','switching','blocked')
def get_migration(db,id):
    m=db.get(Migration,id)
    if not m:raise HTTPException(404,'未找到迁移任务')
    return m
def managed(path):
    # 只允许在留档根目录内操作，根目录外的文件（如 worker 心跳）永不触碰
    try:return Path(path).resolve().is_relative_to(archive.ARCHIVE_ROOT.resolve())
    except OSError:return False
def cleanup_dir(path):
    # 清理被取代代的半成品：只删留档根内 gen-* 目录中的文件
    d=Path(path)
    if not managed(d) or not d.name.startswith('gen-') or not d.is_dir():return
    for f in d.iterdir():
        if f.is_file() and f.name not in archive.PROTECTED_NAMES:f.unlink(missing_ok=True)
    try:d.rmdir()
    except OSError:pass
def supersede_older(db,generation,actor):
    # 并发迁移只允许一代生效：新代登记后，更旧的未完成代立即失效
    for m in db.scalars(select(Migration).where(Migration.state.in_(ACTIVE_STATES),Migration.generation<generation)):
        was_pre_switch=m.state in PRE_SWITCH_STATES
        m.state='superseded';m.blocked_reason='已被更新一代（第 %d 代）取代'%generation;m.updated_at=now()
        if was_pre_switch:cleanup_dir(m.target_dir)
        log(db,actor,'migration.superseded','gen-'+str(m.generation),m.blocked_reason)
def create_migration(db,user):
    pointer=archive.active_pointer(db)
    latest=db.scalars(select(Migration).order_by(Migration.generation.desc()).limit(1)).first()
    generation=(latest.generation if latest else pointer.generation)+1
    if generation<=pointer.generation:generation=pointer.generation+1
    supersede_older(db,generation,user)
    target=archive.gen_dir(generation)
    if target.exists():cleanup_dir(target)
    target.mkdir(parents=True,exist_ok=True)
    m=Migration(generation=generation,state='copying',source_dir=pointer.active_dir,target_dir=str(target),created_by=user.email if hasattr(user,'email') else str(user),created_at=now(),updated_at=now())
    db.add(m);db.flush()
    # 登记本次迁移范围的文件清单；已隔离件不纳入，保留在阻断原因中展示
    items=list(db.scalars(select(ArchiveItem).where(ArchiveItem.state=='ready')))
    for item in items:
        db.add(MigrationFile(migration_id=m.id,item_id=item.id,filename=item.filename,source_path=str(Path(item.directory)/item.filename),target_path=str(target/item.filename),sha256=item.sha256,state='pending',updated_at=now()))
    m.total=len(items)
    log(db,user,'migration.created','gen-'+str(generation),'共 %d 份待迁移'%len(items))
    db.commit();return m
def copy_files(db,m,actor):
    # 逐份复制并核对内容指纹；每份独立提交，中断后再执行沿用已登记件
    files=list(db.scalars(select(MigrationFile).where(MigrationFile.migration_id==m.id,MigrationFile.state!='verified').order_by(MigrationFile.id)))
    for f in files:
        item=db.get(ArchiveItem,f.item_id)
        if item is None or item.state=='quarantined':
            f.state='quarantined';f.error=item.blocked_reason if item else '登记件缺失';f.updated_at=now();db.commit();continue
        try:
            data=archive.authentic_bytes(db,item,actor)
            archive.atomic_write(f.target_path,data)
            if archive.fingerprint(Path(f.target_path).read_bytes())!=f.sha256:raise OSError('目标文件指纹核验未通过')
            f.state='verified';f.error=''
        except HTTPException as e:
            f.state='quarantined';f.error=str(e.detail)[:400]
        except Exception as e:
            f.state='pending';f.error=str(e)[:400]
            m.state='blocked';m.blocked_reason=('复制中断：%s'%e)[:400];m.updated_at=now()
            log(db,actor,'migration.blocked','gen-'+str(m.generation),m.blocked_reason)
        f.updated_at=now();db.commit()
        if m.state=='blocked':return
def refresh_counts(db,m):
    files=list(db.scalars(select(MigrationFile).where(MigrationFile.migration_id==m.id)))
    m.verified=sum(1 for f in files if f.state=='verified')
    m.quarantined=sum(1 for f in files if f.state=='quarantined')
    m.updated_at=now()
def switch_pointer(db,m,actor):
    # 索引切换是代次围栏下的原子比较交换：迟归的旧执行者无法回切
    m.state='switching';m.updated_at=now();db.commit()
    result=db.execute(update(ArchivePointer).where(ArchivePointer.id==1,ArchivePointer.generation<m.generation).values(active_dir=m.target_dir,generation=m.generation,updated_at=now()))
    if result.rowcount!=1:
        db.rollback()
        pointer=db.get(ArchivePointer,1)
        if pointer.generation==m.generation and pointer.active_dir==m.target_dir:
            pass# 同代执行者已完成切换，本代继续后续阶段
        else:
            m.state='superseded';m.blocked_reason='生效索引已由更新一代接管，本代迟归不再回切';m.updated_at=now()
            cleanup_dir(m.target_dir)
            log(db,actor,'migration.superseded','gen-'+str(m.generation),m.blocked_reason);db.commit();return False
    for f in db.scalars(select(MigrationFile).where(MigrationFile.migration_id==m.id,MigrationFile.state=='verified')):
        item=db.get(ArchiveItem,f.item_id)
        if item and item.state=='ready':item.directory=m.target_dir;item.generation=m.generation;item.updated_at=now()
    m.state='switched';m.updated_at=now()
    log(db,actor,'migration.switched','gen-'+str(m.generation),'索引已指向 '+m.target_dir)
    db.commit();return True
def sweep_candidates(db,pointer):
    # 回收候选：陈旧代目录里不再被任何登记件引用的文件；登记件的当前位置永不删除
    protected={(Path(i.directory)/i.filename).as_posix() for i in db.scalars(select(ArchiveItem))}
    active=Path(pointer.active_dir).as_posix();out=[]
    root=archive.ARCHIVE_ROOT
    if not root.is_dir():return out
    for d in root.iterdir():
        if not d.is_dir() or not d.name.startswith('gen-') or d.as_posix()==active:continue
        for f in d.iterdir():
            if f.is_file() and f.name not in archive.PROTECTED_NAMES and f.as_posix() not in protected:out.append(f)
    return out
def reclaim(db,m,actor):
    # 旧件等在途下载结束才回收；只删不再被引用的旧件，共用与受保护文件不误删
    pointer=archive.active_pointer(db)
    candidates=sweep_candidates(db,pointer)
    leased={x.path for x in archive.open_leases(db)}
    waiting=[p for p in candidates if p.as_posix() in leased]
    if waiting:
        m.blocked_reason='等待 %d 个在途下载结束后回收旧件'%len(waiting);m.updated_at=now();db.commit();return
    m.blocked_reason=''
    for p in candidates:p.unlink(missing_ok=True)
    active=Path(pointer.active_dir).as_posix()
    for d in archive.ARCHIVE_ROOT.iterdir():
        if d.is_dir() and d.name.startswith('gen-') and d.as_posix()!=active and not any(d.iterdir()):
            try:d.rmdir()
            except OSError:pass
    m.state='completed';m.updated_at=now()
    log(db,actor,'migration.completed','gen-'+str(m.generation),'旧件已回收，第 %d 代生效'%m.generation)
    db.commit()
def advance(db,migration_id,actor='system'):
    m=get_migration(db,migration_id) if isinstance(migration_id,int) else migration_id
    if m.state not in RESUMABLE_STATES:return m
    pointer=archive.active_pointer(db)
    if pointer.generation>m.generation:
        m.state='superseded';m.blocked_reason='生效索引已更新，本代迟归不再回切';m.updated_at=now()
        cleanup_dir(m.target_dir);db.commit();return m
    if m.state=='switching':
        # 中断恢复：按生效索引校正切换中途的状态
        m.state='switched' if pointer.generation==m.generation else 'copied';m.updated_at=now();db.commit()
    if m.state in ('copying','blocked'):
        m.state='copying';m.blocked_reason='';m.updated_at=now();db.commit()
        copy_files(db,m,actor)
        refresh_counts(db,m);db.commit()
        if m.state=='blocked':return m
        pending=db.scalar(select(MigrationFile.id).where(MigrationFile.migration_id==m.id,MigrationFile.state=='pending'))
        if pending:return m
        m.state='copied';m.updated_at=now()
        log(db,actor,'migration.copied','gen-'+str(m.generation),'已核验 %d/%d 份'%(m.verified,m.total));db.commit()
    if m.state in ('copied','switching'):
        if not switch_pointer(db,m,actor):return m
    if m.state in ('switched','reclaiming'):
        m.state='reclaiming';m.updated_at=now();db.commit()
        reclaim(db,m,actor)
    refresh_counts(db,m);db.commit();return m
def advance_locked(db,migration_id,actor):
    # 同一代只允许一个执行者推进；锁不可用时由数据库代次围栏兜底
    token=secrets.token_hex(8);key='migration:lock:%d'%migration_id;locked=False
    try:locked=bool(queue.set(key,token,nx=True,ex=300))
    except Exception:logging.exception('migration lock unavailable; fencing still enforced')
    if not locked:
        try:
            if queue.get(key):raise HTTPException(409,'该代迁移正在执行中，请稍后重试')
        except HTTPException:raise
        except Exception:pass
    try:return advance(db,migration_id,actor)
    finally:
        try:
            if locked and queue.get(key)==token.encode():queue.delete(key)
        except Exception:pass
def recover(db):
    # 中断恢复：切换中途崩溃的代按生效索引校正，其余停留在已提交的检查点等待继续
    pointer=archive.active_pointer(db)
    for m in db.scalars(select(Migration).where(Migration.state=='switching')):
        m.state='switched' if pointer.generation==m.generation else 'copied'
        m.updated_at=now()
    db.commit()
