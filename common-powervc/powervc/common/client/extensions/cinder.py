# Copyright 2013 IBM Corp.

import six
import urllib

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

from cinderclient import base as client_base
from cinderclient.v1 import volumes
from cinderclient.v1 import volume_types
from powervc.common.client.extensions import base
from powervc.common import utils


class Client(base.ClientExtension):

    def __init__(self, client):
        super(Client, self).__init__(client)
        # Initialize Storage Provider Manager
        self.storage_providers = StorageProviderManager(client)
        # Initialize PVC specified Volume Manager
        self.volumes = PVCVolumeManager(client)
        # Initialize PVC specified StorageTemplate Manager
        self.volume_types = PVCStorageTemplateManager(client)
    # any extensions to std cinder client go below


class StorageProvider(client_base.Resource):
    """
    Entity class for StorageProvider
    """
    def __repr__(self):
        return ("<StorageProvider: %s, storage_hostname: %s>" %
                (self.id, self.storage_hostname))


class StorageProviderManager(client_base.Manager):
    """
    Manager class for StorageProvider
    Currently get and list functions for StorageProvider
    are implemented.
    """
    resource_class = StorageProvider

    def get(self, spUUID):
        """
        Get a StorageProvider.

        :param server: UUID `StorageProvider` to get.
        :rtype: :class:`Server`
        """
        return self._get("/storage-providers/%s" % spUUID,
                         "storage_provider")

    def list(self, detailed=True, search_opts=None,
             scgUUID=None,
             scgName=None):
        """
        Get a list of the Storage Template that filtered by a specified
        SCG UUID or SCG name, if both SCG UUID and SCG name are specified,
        UUID has the high priority to check.

        :rtype: list of :class:`StorageProvider`
        """
        # Get accessible volumes by SCG
        if scgUUID or scgName:
            return (utils.get_utils().
                    get_scg_accessible_storage_providers(
                        scgUUID=scgUUID, scgName=scgName,
                        detailed=detailed, search_opts=search_opts)
                    )
        else:
            return (utils.get_utils().
                    get_multi_scg_accessible_storage_providers(
                        None, None, detailed=detailed, search_opts=search_opts)
                    )

    def list_all_providers(self, detailed=True, search_opts=None):
        """
        Get a list of StorageProvider.
        Optional detailed returns details StorageProvider info.

        :rtype: list of :class:`StorageProvider`
        """
        if search_opts is None:
            search_opts = {}

        qparams = {}

        for opt, val in six.iteritems(search_opts):
            if val:
                qparams[opt] = val

        query_string = "?%s" % urllib.urlencode(qparams) if qparams else ""

        detail = ""
        if detailed:
            detail = "/detail"
        return self._list("/storage-providers%s%s" %
                          (detail, query_string),
                          "storage_providers")


class PVCVolumeManager(volumes.VolumeManager):
    """
    The PVC specified VolumeManager that got and list volumes
    which filtered by Storage Connectivity Group
    """
    def list(self, detailed=True, search_opts=None,
             scgUUID=None,
             scgName=None):
        """
        Get a list of the volumes that filtered by a specified SCG UUID
        or SCG name, if both SCG UUID and SCG name are specified, UUID has the
        high priority to check.

        :rtype: list of :class:`Volume`
        """
        # Get accessible volumes by SCG
        if scgUUID or scgName:
            return (utils.get_utils().
                    get_scg_accessible_volumes(scgUUID=scgUUID,
                                               scgName=scgName,
                                               detailed=detailed,
                                               search_opts=search_opts))
        else:
            return (utils.get_utils().
                    get_multi_scg_accessible_volumes(None,
                                                     None,
                                                     detailed=detailed,
                                                     search_opts=search_opts)
                    )

    def list_all_volumes(self, detailed=True, search_opts=None):
        """
        Get a list of all volumes.

        :rtype: list of :class:`Volume`
        """
        if search_opts is None:
            search_opts = {}

        qparams = {}

        for opt, val in six.iteritems(search_opts):
            if val:
                qparams[opt] = val

        query_string = "?%s" % urlencode(qparams) if qparams else ""

        detail = ""
        if detailed:
            detail = "/detail"

        return self._list("/volumes%s%s" % (detail, query_string),
                          "volumes")

    def create(self, size, snapshot_id=None, source_volid=None,
               display_name=None, display_description=None,
               volume_type=None, user_id=None,
               project_id=None, availability_zone=None,
               metadata=None, imageRef=None, multiattach=False):
        """
        Creates a pvc volume with multiattach specified.

        :param size: Size of volume in GB
        :param snapshot_id: ID of the snapshot
        :param display_name: Name of the volume
        :param display_description: Description of the volume
        :param volume_type: Type of volume
        :param user_id: User id derived from context
        :param project_id: Project id derived from context
        :param availability_zone: Availability Zone to use
        :param metadata: Optional metadata to set on volume creation
        :param imageRef: reference to an image stored in glance
        :param multiattach: if enable the multiattach
        :rtype: :class:`Volume`
        """

        if metadata is None:
            volume_metadata = {}
        else:
            volume_metadata = metadata

        body = {'volume': {'size': size,
                           'snapshot_id': snapshot_id,
                           'display_name': display_name,
                           'display_description': display_description,
                           'volume_type': volume_type,
                           'user_id': user_id,
                           'project_id': project_id,
                           'availability_zone': availability_zone,
                           'status': "creating",
                           'attach_status': "detached",
                           'metadata': volume_metadata,
                           'imageRef': imageRef,
                           'source_volid': source_volid,
                           'multiattach': multiattach
                           }}
        return self._create('/volumes', body, 'volume')

class PVCStorageTemplateManager(volume_types.VolumeTypeManager):
    """
    The PVC specified StorageTemplateManager that list Storage Templates
    (VolumeType in OpenStack) which filtered by Storage Connectivity Group
    """

    def list(self, scgUUID=None, scgName=None):
        """
        Get a list of the Storage Template that filtered by a specified
        SCG UUID or SCG name, if both SCG UUID and SCG name are specified,
        UUID has the high priority to check.

        :rtype: list of :class:`VolumeType`
        """
        # Get accessible volumes by SCG
        if scgUUID or scgName:
            return (utils.get_utils().
                    get_scg_accessible_storage_templates(scgUUID=scgUUID,
                                                         scgName=scgName))
        else:
            return (utils.get_utils().
                    get_multi_scg_accessible_storage_templates(None,
                                                               None))

    def list_all_storage_templates(self):
        """
        Get a list of all Storage Templates

        :rtype: list of :class:`VolumeType`.
        """
        return self._list("/types", "volume_types")
