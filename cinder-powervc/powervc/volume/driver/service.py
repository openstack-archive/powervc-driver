from __future__ import absolute_import
COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import httplib

from cinderclient import exceptions
from cinder.openstack.common import log as logging
from powervc.common import constants as common_constants
from powervc.common.gettextutils import _
from powervc.volume.manager import constants
from cinder import exception
from cinder import db
from cinder import context
from cinder.openstack.common import loopingcall

LOG = logging.getLogger(__name__)


class PowerVCService(object):

    """A service that exposes PowerVC functionality.
    The services provided here are called by the driver.
    The services leverage the nova client to interface to the PowerVC.
    This design keeps the driver and client interface clean and simple
    and provides a workspace for any data manipulation and utility work
    that may need to be done.
    """
    _client = None

    def __init__(self, pvc_client=None):
        """Initializer."""
        from powervc.common.client import factory
        if(PowerVCService._client is None):
            PowerVCService._client = \
                factory.POWERVC.new_client(
                    str(common_constants.SERVICE_TYPES.volume))

        # Add version checking as required

    def create_volume(self, local_volume_id, size, snapshot_id=None,
                      source_volid=None,
                      display_name=None, display_description=None,
                      volume_type=None, user_id=None,
                      project_id=None, availability_zone=None,
                      metadata=None, imageRef=None):
        """
        Creates a volume on powervc
        """

        # Use the standard cinderclient to create volume
        # TODO Do not pass metadata to PowerVC currently as we don't
        # know if this has a conflict with PowerVC design.
        pvc_volume = PowerVCService._client.volumes.create(size,
                                                           snapshot_id,
                                                           source_volid,
                                                           display_name,
                                                           display_description,
                                                           volume_type,
                                                           user_id,
                                                           project_id,
                                                           availability_zone,
                                                           {},
                                                           imageRef)

        # update powervc uuid to db immediately to avoid duplicated
        # synchronization
        additional_volume_data = {}
        additional_volume_data['metadata'] = metadata
        additional_volume_data['metadata'][constants.LOCAL_PVC_PREFIX + 'id'] \
            = pvc_volume.id
        db.volume_update(context.get_admin_context(),
                         local_volume_id,
                         additional_volume_data)
        LOG.info(_("Volume %s start to create with PVC UUID: %s"),
                 local_volume_id, pvc_volume.id)

        temp_status = getattr(pvc_volume, 'status', None)
        if temp_status == constants.STATUS_CREATING:
            LOG.debug(_(
                'wait until created volume status is available or ERROR'))
            timer = loopingcall.FixedIntervalLoopingCall(
                self._wait_for_state_change, pvc_volume.id,
                getattr(pvc_volume, 'status', None),
                constants.STATUS_AVAILABLE,
                constants.STATUS_CREATING)

            try:
                timer.start(interval=10).wait()
                # set status to available
                additional_volume_data['status'] = \
                    constants.STATUS_AVAILABLE
            except:
                latest_pvc_volume = PowerVCService._client.volumes.get(
                    pvc_volume.id)
                additional_volume_data['status'] = getattr(latest_pvc_volume,
                                                           'status', '')
        else:
            LOG.debug(_('Not in creating status, just set as powerVC status'))
            additional_volume_data['status'] = temp_status

        # return updated volume status information
        return additional_volume_data

    def _wait_for_state_change(self, volume_id, original_state, expected_state,
                               middle_state):
        """
        Utility method to wait for a volume to change to the
        expected state.
        The process of some operation contains three states.

        during the operation. If the operation has no middle state,
        it can be set as original state.
        """
        volume = None
        try:
            volume = PowerVCService._client.volumes.get(volume_id)
        except exceptions.NotFound:
            raise exception.VolumeNotFound('volume not found: %s' %
                                           volume_id)

        if volume.status == expected_state:
            LOG.debug(
                "Operation %(vm_id)s successfully, " +
                "status changed to %(state)s"
                % {'vm_id': volume.id, 'state': expected_state})
            raise loopingcall.LoopingCallDone()
        if (volume.status != original_state and
            volume.status != expected_state and
                volume.status != middle_state):
            raise exception.InvalidVolume()

    def delete_volume(self, pvc_volume_id):
        """
        Deletes the specified powervc volume id from powervc
        """
        LOG.debug(_("Deleting pvc volume: %s"), pvc_volume_id)
        if not pvc_volume_id:
            raise AttributeError(_("Powervc volume identifier must be "
                                   "specified"))
        existed_pvc_volume = None
        try:
            existed_pvc_volume = PowerVCService._client.volumes.get(
                pvc_volume_id)
        except exceptions.NotFound:
            LOG.critical(_("pvc: %s no longer existed in powervc, ignore"),
                         pvc_volume_id)
            raise

        temp_status = getattr(existed_pvc_volume, 'status', None)
        if temp_status == constants.STATUS_DELETING:
            # Volume in deleting status, do not perform delete operation
            # again
            LOG.warning(
                _("pvc: %s is deleting in powervc, wait for status"),
                pvc_volume_id)
        else:
            # volume available for deleting, perform delete opeartion
            PowerVCService._client.volumes.delete(pvc_volume_id)

        LOG.debug(_(
            'wait until created volume deleted or status is ERROR'))
        timer = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_state_change, existed_pvc_volume.id,
            getattr(existed_pvc_volume, 'status', None),
            '',
            constants.STATUS_DELETING)

        try:
            timer.start(interval=10).wait()
        except exception.VolumeNotFound:
            # deleted complete
            LOG.info(_("pvc: %s deleted successfully"),
                     pvc_volume_id)
        except exception.InvalidVolume:
            LOG.critical(_("pvc: %s deleted failed, "),
                         pvc_volume_id)
            # when delete failed raise exception
            raise exception.CinderException(
                _('Volume deletion failed for id: %s'),
                pvc_volume_id)

    def _validate_response(self, response):
        """
        Validates an HTTP response to a REST API request made by this service.

        The method will simply return if the HTTP error code indicates success
        (i.e. between 200 and 300).
        Any other errors, this method will raise the exception.
        Note: Appropriate exceptions to be added...
        Nova client throws an exception for 404

        :param response: the HTTP response to validate
        """
        if response is None:
            return
        httpResponse = response[0]
        # Any non-successful response >399 is an error
        if httpResponse.status_code >= httplib.BAD_REQUEST:
            LOG.critical(_("Service: got this response: %s")
                         % httpResponse)
            LOG.debug("Service: got this response: %s"
                      % httpResponse)
            raise exceptions.BadRequest(httpResponse)

    def list_volume_types(self):
        return PowerVCService._client.volume_types.list()

    def get_volume_type(self, vol_type_id):
        return PowerVCService._client.volume_types.get(vol_type_id)

    def get_volume_type_by_name(self, volume_type_name):
        pvc_volume_type = None

        if volume_type_name is None or PowerVCService._client is None:
            return pvc_volume_type

        pvc_volume_type_list = self.list_volume_types()

        if pvc_volume_type_list is None:
            return volume_type_name

        for volume_type in pvc_volume_type_list:
            if volume_type_name == volume_type._info["name"]:
                pvc_volume_type = volume_type
                break

        return pvc_volume_type

    def get_volumes(self):
        pvc_volumes = None

        if PowerVCService._client is None:
            return pvc_volumes

        pvc_volumes = PowerVCService._client.volumes.list()

        return pvc_volumes

    def get_volume_by_name(self, display_name):
        pvc_volume = None

        if display_name is None or PowerVCService._client is None:
            return pvc_volume

        pvc_volume_list = self.get_volumes()
        if pvc_volume_list is None:
            return pvc_volume

        for volume in pvc_volume_list:
            if display_name == volume._info["display_name"]:
                pvc_volume = volume
                break

        return pvc_volume

    def get_volume_by_id(self, volume_id):
        pvc_volume = None

        if volume_id is None or PowerVCService._client is None:
            return pvc_volume

        try:
            pvc_volume = PowerVCService._client.volumes.get(volume_id)
        except exceptions.NotFound:
            LOG.debug("get_volume_by_id volume %s not found"
                      % volume_id)
            pvc_volume = None

        return pvc_volume

    def list_storage_providers(self):
        return PowerVCService._client.storage_providers.list()
