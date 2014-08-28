# Copyright 2013, 2014 IBM Corp.

import sqlalchemy as sql
from sqlalchemy.orm import exc

import neutron.db.api as db_api
from neutron.openstack.common import log as logging

from powervc.common.gettextutils import _
from powervc.neutron.common import constants
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_models_v2 as model

LOG = logging.getLogger(__name__)


class PowerVCAgentDB(object):
    """PowerVC Agent DB access methods"""

    def __init__(self):
        self.session = db_api.get_session()
        self.register_models()

    def register_models(self):
        """Register Models and create properties."""
        try:
            engine = db_api.get_engine()
            model.PowerVCMapping.metadata.create_all(engine)
        except sql.exc.OperationalError as e:
            LOG.info(_("Database registration exception: %s"), e)

    def _create_object(self, obj_type, sync_key, update_data=None,
                       local_id=None, pvc_id=None):
        """Create mapping entry for a Neutron object"""
        with self.session.begin(subtransactions=True):
            obj = model.PowerVCMapping(obj_type, sync_key)
            if local_id:
                obj.local_id = local_id
            if pvc_id:
                obj.pvc_id = pvc_id
            if local_id and pvc_id:
                obj.status = constants.STATUS_ACTIVE
            if update_data:
                obj.update_data = update_data
            self.session.add(obj)
        LOG.info(_("Created %(obj_type)s %(sync_key)s for "
                   "local id %(local_id)s and pvc id %(pvc_id)s"),
                 {'obj_type': obj_type,
                  'sync_key': obj.sync_key,
                  'local_id': obj.local_id,
                  'pvc_id': obj.pvc_id})
        return obj

    def _delete_object(self, obj):
        """Delete a mapping object"""
        if not obj:
            return
        try:
            obj_id = obj['id']
            existing = (self.session.query(model.PowerVCMapping).
                        filter_by(id=obj_id).one())
        except exc.NoResultFound:
            existing = None
            LOG.warning(_("Object not found in DB: %(object)s"),
                        {'object': obj})
        if existing:
            with self.session.begin(subtransactions=True):
                self.session.delete(existing)
            LOG.info(_("Deleted %(obj_type)s %(sync_key)s for "
                       "local id %(local_id)s and pvc id %(pvc_id)s"),
                     {'obj_type': existing.obj_type,
                      'sync_key': existing.sync_key,
                      'local_id': existing.local_id,
                      'pvc_id': existing.pvc_id})

    def _get_objects(self, obj_type, status=None):
        """Retrieve all mappings for a given object type and status"""
        try:
            if status:
                objects = (self.session.query(model.PowerVCMapping).
                           filter_by(obj_type=obj_type,
                                     status=status).all())
            else:
                objects = (self.session.query(model.PowerVCMapping).
                           filter_by(obj_type=obj_type).all())
        except exc.NoResultFound:
            objects = None
        return objects

    def _get_object(self, obj_type, obj_id=None, local_id=None, pvc_id=None,
                    sync_key=None):
        """Retrieve the object with the specified type and id"""
        try:
            if obj_id:
                obj = (self.session.query(model.PowerVCMapping).
                       filter_by(obj_type=obj_type, id=obj_id).one())
            elif local_id:
                obj = (self.session.query(model.PowerVCMapping).
                       filter_by(obj_type=obj_type, local_id=local_id).one())
            elif pvc_id:
                obj = (self.session.query(model.PowerVCMapping).
                       filter_by(obj_type=obj_type, pvc_id=pvc_id).one())
            elif sync_key:
                obj = (self.session.query(model.PowerVCMapping).
                       filter_by(obj_type=obj_type, sync_key=sync_key).one())
            else:
                obj = None
        except exc.NoResultFound:
            obj = None
        return obj

    def _get_object_stats(self, obj_type):
        """Retrieve counts for the specified object type"""
        try:
            creating = (self.session.query(model.PowerVCMapping).
                        filter_by(obj_type=obj_type,
                                  status=constants.STATUS_CREATING).count())
            active = (self.session.query(model.PowerVCMapping).
                      filter_by(obj_type=obj_type,
                                status=constants.STATUS_ACTIVE).count())
            deleting = (self.session.query(model.PowerVCMapping).
                        filter_by(obj_type=obj_type,
                                  status=constants.STATUS_DELETING).count())
        except exc.NoResultFound:
            return (0, 0, 0)
        return (creating, active, deleting)

    def _set_object_pvc_id(self, obj, pvc_id):
        """Update object with the pvc_id field"""
        if not obj:
            return
        try:
            obj_id = obj['id']
            obj = (self.session.query(model.PowerVCMapping).
                   filter_by(id=obj_id).one())
            if pvc_id and obj['pvc_id']:
                LOG.warning(_("Field in database entry is already set. "
                              "Unable to set pvc id %s into database "
                              "entry %s"), pvc_id, obj)
                return
            obj['pvc_id'] = pvc_id
            if pvc_id:
                if obj['local_id']:
                    obj['status'] = constants.STATUS_ACTIVE
                else:
                    obj['status'] = constants.STATUS_CREATING
            else:
                if obj['local_id']:
                    obj['status'] = constants.STATUS_DELETING
                else:
                    self._delete_object(obj)
                    return
            self.session.merge(obj)
            self.session.flush
            LOG.info(_("Updated %(obj_type)s %(sync_key)s for "
                       "local id %(local_id)s and pvc id %(pvc_id)s"),
                     {'obj_type': obj.obj_type,
                      'sync_key': obj.sync_key,
                      'local_id': obj.local_id,
                      'pvc_id': obj.pvc_id})
            return
        except exc.NoResultFound:
            LOG.warning(_("Object not found"))
            return

    def _set_object_local_id(self, obj, local_id):
        """Update object with the specific fields"""
        if not obj:
            return
        try:
            obj_id = obj['id']
            obj = (self.session.query(model.PowerVCMapping).
                   filter_by(id=obj_id).one())
            if local_id and obj['local_id']:
                LOG.warning(_("Field in database entry is already set. "
                              "Unable to set local id %s into database "
                              "entry %s"), local_id, obj)
                return
            obj['local_id'] = local_id
            if local_id:
                if obj['pvc_id']:
                    obj['status'] = constants.STATUS_ACTIVE
                else:
                    obj['status'] = constants.STATUS_CREATING
            else:
                if obj['pvc_id']:
                    obj['status'] = constants.STATUS_DELETING
                else:
                    self._delete_object(obj)
                    return
            self.session.merge(obj)
            self.session.flush
            LOG.info(_("Updated %(obj_type)s %(sync_key)s for "
                       "local id %(local_id)s and pvc id %(pvc_id)s"),
                     {'obj_type': obj.obj_type,
                      'sync_key': obj.sync_key,
                      'local_id': obj.local_id,
                      'pvc_id': obj.pvc_id})
            return
        except exc.NoResultFound:
            LOG.warning(_("Object not found"))
            return

    def _set_object_update_data(self, obj, update_data):
        """Update object with the specific fields"""
        if not obj:
            return
        try:
            obj_id = obj['id']
            obj = (self.session.query(model.PowerVCMapping).
                   filter_by(id=obj_id).one())
            obj['update_data'] = update_data
            self.session.merge(obj)
            self.session.flush
            LOG.info(_("Updated %(obj_type)s %(sync_key)s with new "
                       "update data %(update_data)s"),
                     {'obj_type': obj.obj_type,
                      'sync_key': obj.sync_key,
                      'update_data': obj.update_data})
            return obj
        except exc.NoResultFound:
            LOG.warning(_("Object not found"))
            return None

    def fix_incorrect_state(self, obj):
        """Correct state error on the database entry"""
        LOG.warning(_("DB entry is not in correct state: %s"), obj)
        if not obj:
            return
        try:
            obj_id = obj['id']
            obj = (self.session.query(model.PowerVCMapping).
                   filter_by(id=obj_id).one())
            if obj['pvc_id'] and obj['local_id']:
                obj['status'] = constants.STATUS_ACTIVE
                LOG.info(_("Updated DB entry state: %s"), obj)
            self.session.merge(obj)
            self.session.flush
        except exc.NoResultFound:
            LOG.warning(_("Object not found"))
            return None

    def create_network(self, net, sync_key, local_id=None, pvc_id=None):
        return self._create_object(constants.OBJ_TYPE_NETWORK, sync_key,
                                   utils.gen_network_update_data(net),
                                   local_id, pvc_id)

    def delete_network(self, obj):
        return self._delete_object(obj)

    def get_networks(self, status=None):
        return self._get_objects(constants.OBJ_TYPE_NETWORK, status)

    def get_network(self, obj_id=None, local_id=None, pvc_id=None,
                    sync_key=None):
        return self._get_object(constants.OBJ_TYPE_NETWORK, obj_id=obj_id,
                                local_id=local_id, pvc_id=pvc_id,
                                sync_key=sync_key)

    def get_network_stats(self):
        return self._get_object_stats(constants.OBJ_TYPE_NETWORK)

    def set_network_pvc_id(self, obj, pvc_id):
        return self._set_object_pvc_id(obj, pvc_id)

    def set_network_local_id(self, obj, local_id):
        return self._set_object_local_id(obj, local_id)

    def set_network_update_data(self, obj, update_data):
        return self._set_object_update_data(obj, update_data)

    def create_subnet(self, sub, sync_key, local_id=None, pvc_id=None):
        return self._create_object(constants.OBJ_TYPE_SUBNET, sync_key,
                                   utils.gen_subnet_update_data(sub),
                                   local_id, pvc_id)

    def delete_subnet(self, obj):
        return self._delete_object(obj)

    def get_subnets(self, status=None):
        return self._get_objects(constants.OBJ_TYPE_SUBNET, status)

    def get_subnet(self, obj_id=None, local_id=None, pvc_id=None,
                   sync_key=None):
        return self._get_object(constants.OBJ_TYPE_SUBNET, obj_id=obj_id,
                                local_id=local_id, pvc_id=pvc_id,
                                sync_key=sync_key)

    def get_subnet_stats(self):
        return self._get_object_stats(constants.OBJ_TYPE_SUBNET)

    def set_subnet_pvc_id(self, obj, pvc_id):
        return self._set_object_pvc_id(obj, pvc_id)

    def set_subnet_local_id(self, obj, local_id):
        return self._set_object_local_id(obj, local_id)

    def set_subnet_update_data(self, obj, update_data):
        return self._set_object_update_data(obj, update_data)

    def create_port(self, port, sync_key, local_id=None, pvc_id=None):
        return self._create_object(constants.OBJ_TYPE_PORT, sync_key,
                                   utils.gen_port_update_data(port),
                                   local_id, pvc_id)

    def delete_port(self, obj):
        return self._delete_object(obj)

    def get_ports(self, status=None):
        return self._get_objects(constants.OBJ_TYPE_PORT, status)

    def get_port(self, obj_id=None, local_id=None, pvc_id=None,
                 sync_key=None):
        return self._get_object(constants.OBJ_TYPE_PORT, obj_id=obj_id,
                                local_id=local_id, pvc_id=pvc_id,
                                sync_key=sync_key)

    def get_port_stats(self):
        return self._get_object_stats(constants.OBJ_TYPE_PORT)

    def set_port_pvc_id(self, obj, pvc_id):
        return self._set_object_pvc_id(obj, pvc_id)

    def set_port_local_id(self, obj, local_id):
        return self._set_object_local_id(obj, local_id)

    def set_port_update_data(self, obj, update_data):
        return self._set_object_update_data(obj, update_data)
