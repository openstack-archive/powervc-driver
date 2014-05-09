# Copyright 2013 IBM Corp.

import sqlalchemy as sa

from neutron.db import model_base
from neutron.openstack.common import uuidutils
from powervc.neutron.common import constants


class PowerVCMapping(model_base.BASEV2):
    """Represents mapping between local OS and PowerVC Neutron object"""
    id = sa.Column(sa.String(36),
                   primary_key=True,
                   default=uuidutils.generate_uuid)
    obj_type = sa.Column(sa.Enum(constants.OBJ_TYPE_NETWORK,
                                 constants.OBJ_TYPE_SUBNET,
                                 constants.OBJ_TYPE_PORT,
                                 name='mapping_object_type'),
                         nullable=False)
    status = sa.Column(sa.Enum(constants.STATUS_CREATING,
                               constants.STATUS_ACTIVE,
                               constants.STATUS_DELETING,
                               name='mapping_state'),
                       nullable=False)
    sync_key = sa.Column(sa.String(255), nullable=False)
    local_id = sa.Column(sa.String(36))
    pvc_id = sa.Column(sa.String(36))
    update_data = sa.Column(sa.String(512))

    def __init__(self, obj_type, sync_key):
        self.obj_type = obj_type
        self.status = constants.STATUS_CREATING
        self.sync_key = sync_key
