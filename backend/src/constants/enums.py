from enum import Enum
class Role(str,Enum):
    admin='admin'; analyst='analyst'; viewer='viewer'
class RunState(str,Enum):
    queued='queued'; running='running'; completed='completed'; failed='failed'
class ReviewState(str,Enum):
    draft='draft'; approved='approved'
class ArchiveItemState(str,Enum):
    ready='ready'; quarantined='quarantined'
class MigrationState(str,Enum):
    copying='copying'; copied='copied'; switching='switching'; switched='switched'; reclaiming='reclaiming'; completed='completed'; blocked='blocked'; superseded='superseded'; failed='failed'
class MigrationFileState(str,Enum):
    pending='pending'; copied='copied'; verified='verified'; quarantined='quarantined'
