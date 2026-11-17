from sqlalchemy import Column,Integer,String,ForeignKey,UniqueConstraint
from ..config.database import Base
class ArchiveItem(Base):
    __tablename__='archive_items'
    __table_args__=(UniqueConstraint('kind','ref_id',name='uq_archive_item'),)
    id=Column(Integer,primary_key=True)
    kind=Column(String(20),nullable=False)
    ref_id=Column(Integer,nullable=False)
    filename=Column(String(160),nullable=False)
    sha256=Column(String(64),nullable=False)
    bytes=Column(Integer,nullable=False)
    state=Column(String(20),default='ready')
    blocked_reason=Column(String(400),default='')
    directory=Column(String(400),nullable=False)
    generation=Column(Integer,nullable=False,default=0)
    repairs=Column(Integer,default=0)
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)
class Migration(Base):
    __tablename__='migrations'
    id=Column(Integer,primary_key=True)
    generation=Column(Integer,unique=True,nullable=False)
    state=Column(String(20),default='copying')
    source_dir=Column(String(400),nullable=False)
    target_dir=Column(String(400),nullable=False)
    blocked_reason=Column(String(400),default='')
    total=Column(Integer,default=0)
    verified=Column(Integer,default=0)
    quarantined=Column(Integer,default=0)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)
class MigrationFile(Base):
    __tablename__='migration_files'
    __table_args__=(UniqueConstraint('migration_id','item_id',name='uq_migration_file'),)
    id=Column(Integer,primary_key=True)
    migration_id=Column(Integer,ForeignKey('migrations.id'),nullable=False)
    item_id=Column(Integer,ForeignKey('archive_items.id'),nullable=False)
    filename=Column(String(160),nullable=False)
    source_path=Column(String(500),nullable=False)
    target_path=Column(String(500),nullable=False)
    sha256=Column(String(64),nullable=False)
    state=Column(String(20),default='pending')
    error=Column(String(400),default='')
    updated_at=Column(String(40),nullable=False)
class ArchivePointer(Base):
    __tablename__='archive_pointer'
    id=Column(Integer,primary_key=True)
    active_dir=Column(String(400),nullable=False)
    generation=Column(Integer,nullable=False,default=0)
    updated_at=Column(String(40),nullable=False)
class DownloadLease(Base):
    __tablename__='download_leases'
    id=Column(Integer,primary_key=True)
    item_id=Column(Integer,ForeignKey('archive_items.id'),nullable=False)
    generation=Column(Integer,nullable=False)
    path=Column(String(500),nullable=False)
    started_at=Column(String(40),nullable=False)
    finished_at=Column(String(40),nullable=True)
