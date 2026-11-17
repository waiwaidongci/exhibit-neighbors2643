from ..services import archive,migration
class ArchiveController:
    overview=staticmethod(archive.overview)
    @staticmethod
    def create(db,user):
        m=migration.create_migration(db,user)
        migration.advance_locked(db,m.id,user)
        return archive.overview(db)
    @staticmethod
    def advance(db,user,id):
        migration.advance_locked(db,id,user)
        return archive.overview(db)
