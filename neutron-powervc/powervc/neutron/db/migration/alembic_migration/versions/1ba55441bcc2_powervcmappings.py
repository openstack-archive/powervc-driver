"""create powervcmappings tables

Revision ID: 1ba55441bcc2
Revises: None
Create Date: 2014-08-27 16:24:01.765923

"""

# revision identifiers, used by Alembic.
revision = '1ba55441bcc2'
down_revision = None

from alembic import op
import sqlalchemy as sa
from oslo.db.sqlalchemy import session
from alembic import util as alembic_util
from alembic import context
from neutron.openstack.common import uuidutils
from powervc.neutron.common import constants

tablename = 'powervcmappings'


def upgrade():
    url = context.config.powervc_config.DATABASE.connection
    engine = session.create_engine(url)
    # In previous release, we do not use alembic or any other migration,
    # as we need to support migration case, we need to check if the table
    # exists or not
    if engine.dialect.has_table(engine.connect(), tablename):
        alembic_util.msg("table has been already exists!")
        return
    op.create_table(
        tablename,
        sa.Column('id', sa.String(36),
                  primary_key=True,
                  default=uuidutils.generate_uuid),
        sa.Column('obj_type', sa.Enum(constants.OBJ_TYPE_NETWORK,
                                      constants.OBJ_TYPE_SUBNET,
                                      constants.OBJ_TYPE_PORT,
                                      name='mapping_object_type'),
                  nullable=False),
        sa.Column('status', sa.Enum(constants.STATUS_CREATING,
                                    constants.STATUS_ACTIVE,
                                    constants.STATUS_DELETING,
                                    name='mapping_state'),
                  nullable=False),
        sa.Column('sync_key', sa.String(255), nullable=False),
        sa.Column('local_id', sa.String(36)),
        sa.Column('pvc_id', sa.String(36)),
        sa.Column('update_data', sa.String(512))
    )


def downgrade():
    op.drop_table(tablename)
