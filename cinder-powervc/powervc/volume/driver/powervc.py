from __future__ import absolute_import
# Copyright 2013, 2014 IBM Corp.
import logging
import sys

from cinder import exception
from oslo_log import log as cinderLogging
from cinder.volume.driver import VolumeDriver
from cinderclient.exceptions import NotFound
from oslo.config import cfg
from powervc.common import config
from powervc.common import constants as common_constants
from powervc.common.gettextutils import _
from powervc.volume.manager import constants
from powervc.volume.driver import service

volume_driver_opts = [

    # Ignore delete errors so an exception is not thrown during a
    # delete.  When set to true, this allows the volume to be deleted
    # on the hosting OS even if an exception occurs. When set to false,
    # exceptions during delete prevent the volume from being deleted
    # on the hosting OS.
    cfg.BoolOpt('volume_driver_ignore_delete_error', default=False)
]

CONF = config.CONF
CONF.register_opts(volume_driver_opts, group='powervc')

LOG = cinderLogging.getLogger(__name__)


def _load_power_config(argv):
    """
    Loads the powervc config.
    """
    # Cinder is typically started with the --config-file option.
    # This prevents the default config files from loading since
    # the olso config code will only load those
    # config files as specified on the command line.
    # If the cinder is started with the
    # --config-file option then append our powervc.conf file to
    # the command line so it gets loaded as well.
    for arg in argv:
        if arg == '--config-file' or arg.startswith('--config-file='):
            argv[len(argv):] = ["--config-file"] + \
                [cfg.find_config_files(project='powervc',
                                       prog='powervc')[0]]
            break

    config.parse_power_config(argv, 'cinder')

_load_power_config(sys.argv)

# must load powervc config before importing factory when
# called with import utils for a driver
from powervc.common.client import factory


class PowerVCDriver(VolumeDriver):

    """
    Implements the cinder volume driver for powerVC
    """

    def __init__(self, *args, **kwargs):
        super(PowerVCDriver, self).__init__(*args, **kwargs)
        CONF.log_opt_values(LOG, logging.INFO)
        self._service = service.PowerVCService()
        if not service.PowerVCService._client:
            service.PowerVCService._client = factory.POWERVC.new_client(str(
                common_constants.SERVICE_TYPES.volume))

    def check_for_setup_error(self):
        """
        Checks for setup errors.  Nothing to do for powervc.
        """
        pass

    def initialize_connection(self, volume, connector):
        """
        Allow connection to connector and return connection info.
        In the PowerVC cinder driver, it does not need to be implemented.
        """
        LOG.debug("Enter - initialize_connection")
        return {'driver_volume_type': '', 'data': {}}
        LOG.debug("Exit - initialize_connection")

    def validate_connector(self, connector):
        """
        Fail if connector doesn't contain all the data needed by driver.
        In the PowerVC cinder driver, it does not need to be implemented.
        """
        return True

    def terminate_connection(self, volume_ref, connector, force):
        """Do nothing since connection is not used"""
        pass

    def create_export(self, context, volume):
        """
        Exports the volume.  Nothing to do for powervc
        """
        pass

    def accept_transfer(self, context, volume_ref, new_user, new_project):
        """
        Accept a volume that has been offered for transfer.
        Nothing to do for powervc
        """
        pass

    def create_cloned_volume(self, volume_ref, srcvol_ref):
        """
        Clone a volume from an existing volume.
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def copy_image_to_volume(self, context, volume_ref, image_service,
                             image_id):
        """
        Copy a glance image to a volume.
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """
        Upload an exsiting volume into powervc as a glance image
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def create_snapshot(self, snapshot_ref):
        """
        Create a snapshot.
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def delete_snapshot(self, snapshot_ref):
        """
        Delete a snapshot.
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def create_volume_from_snapshot(self, volume, snapshot_ref):
        """
        Create a volume from the snapshot.
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def extend_volume(self, volume, new_size):
        """
        Extend a volume size.
        Currently not supported by powervc.
        Add stub to pass tempest.
        """
        pass

    def create_volume(self, volume):
        """
        Creates a volume with the specified volume attributes

        :returns: a dictionary of updates to the volume db, for example
                  adding metadata
        """
        LOG.info(_("Creating volume with volume: %s."), volume)
        size = getattr(volume, 'size', None)
        display_name = getattr(volume, 'display_name', None)
        display_description = getattr(volume, 'display_description', None)
        volume_type_obj = getattr(volume, 'volume_type', None)
        metadatas = getattr(volume, 'volume_metadata', None)
        multiattach = getattr(volume, 'multiattach', False)
        meta = {}
        if metadatas:
            # Use map() to get a list of 'key', 'value' tuple
            # dict() can convert a list of tuple to dict obj
            meta = dict(map(lambda m: (getattr(m, 'key'),
                                       getattr(m, 'value')), metadatas))

        if (size is None):
            raise exception.InvalidVolume(reason='size is None')
        LOG.info(_("Creating volume %s of size %sG."),
                 self._get_vol_name(volume),
                 size)

        volume_data_updates = self._service.create_volume(
            local_volume_id=volume.id,
            size=size,
            display_name=display_name,
            display_description=display_description,
            metadata=meta,
            volume_type=getattr(volume_type_obj, 'id',
                                None),
            multiattach=multiattach)

        return volume_data_updates

    def delete_volume(self, volume):
        """
        Deletes the specfied volume from powervc
        """
        try:
            LOG.info(_("Deleting volume %s."), self._get_vol_name(volume))

            pvc_volume_id = None
            for metaDataItem in volume.volume_metadata:
                if metaDataItem.key == constants.LOCAL_PVC_PREFIX + 'id':
                    pvc_volume_id = metaDataItem.value
                    break

            if pvc_volume_id is not None:
                self._service.delete_volume(pvc_volume_id)
            else:
                LOG.warning(_("Volume metadata does not "
                              "contain a powervc volume identifier."))

        except NotFound:
            LOG.debug(_("Volume id %s was already deleted on powervc"),
                      pvc_volume_id)
            LOG.info(_("Volume %s deleted."), self._get_vol_name(volume))
        except Exception as e:
            if CONF.powervc.volume_driver_ignore_delete_error:
                LOG.error(_("Volume %s deleted, however the following "
                            "error occurred "
                            "which prevented the backing volume in PowerVC "
                            "from being deleted: %s"),
                          self._get_vol_name(volume),
                          str(e))
            else:
                raise

    def ensure_export(self, context, volume):
        """
        Makes sure the volume is exported.  Nothing to do for powervc
        """
        pass

    def remove_export(self, context, volume):
        """
        Removes the export.  Nothing to do for powervc
        """
        pass

    def get_volume_stats(self, refresh=False):
        """
        Gets the volume statistics for this driver.  Cinder periodically calls
        this to get the latest volume stats.  The stats are stored in the
        instance attribute called _stats
        """
        if refresh:
            self._update_volume_status()

        return self._stats

    def _update_volume_status(self):
        """
        Retrieve volumes stats info from powervc.
        For now just make something up
        """
        LOG.debug(_("Getting volume stats from powervc"))

        # get accessible storage providers list
        sp_list = self._list_storage_providers()
        free_capacity_gb = 0
        total_capacity_gb = 0
        for sp in sp_list:
            free_capacity_gb += getattr(sp, 'free_capacity_gb', 0)
            total_capacity_gb += getattr(sp, 'total_capacity_gb', 0)

        data = {}
        data["volume_backend_name"] = constants.POWERVC_VOLUME_BACKEND
        data["vendor_name"] = 'IBM'
        data["driver_version"] = 1.0
        data["storage_protocol"] = 'Openstack'
        data['total_capacity_gb'] = total_capacity_gb
        data['free_capacity_gb'] = free_capacity_gb
        data['reserved_percentage'] = 0
        data['QoS_support'] = False

        self._stats = data
        LOG.debug(self._stats)

    def _list_storage_providers(self):
        return self._service.list_storage_providers()

    def _get_vol_name(self, volume):
        """
        Returns the name of the volume or its id
        """
        name = getattr(volume, 'display_name', None)
        if name:
            return name
        else:
            return volume.id

    def attach_volume(self, context, volume, instance_uuid, host_name,
                      mountpoint):
        """Callback for volume attached to instance or host."""
        # wait for volume to be attached
        self._service.attach_volume(context, volume, instance_uuid, host_name,
                                    mountpoint)

    def detach_volume(self, context, volume, attachment):
        """Callback for volume detached."""
        # wait for volume to be detached
        self._service.detach_volume(context, volume)
