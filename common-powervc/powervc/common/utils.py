# Copyright 2013 IBM Corp.
import logging
import exception
import os
import sys
import threading
import time

from eventlet.semaphore import Semaphore
from glanceclient.openstack.common import importutils
from powervc.common import config
from powervc.common import constants
from powervc.common.exception import StorageConnectivityGroupNotFound
from powervc.common.gettextutils import _

LOG = logging.getLogger(__name__)

CONF = config.CONF
DEFAULT_TTL = 600


class TimeLivedCache(object):
    """
    The base class to provide the functionality of a timed cache.
    The default refresh time is 10 mins.
    """
    def __init__(self, ttl=DEFAULT_TTL):
        self._cache = {}
        self._last_updated = -1
        self._lock = threading.Lock()
        self.ttl = ttl

    def _cache_resources(self):
        """
        Refreshes the cached values if the cached time has expired,
        or if there are no cached values.
        """
        now = round(time.time())
        if now - self._last_updated < self.ttl and len(self._cache) != 0:
            return
        with self._lock:
            if now - self._last_updated < self.ttl:
                return
            self._cache = self._get_cache()
            LOG.debug(_("Updated %s at %s. Last update: %s") %
                      (str(self), now, self._last_updated))
            self._last_updated = now

    def _get_cache(self):
        tmp_cache = {}
        resources = self._get_resources()
        if resources:
            for resource in resources:
                tmp_cache[self._id_for_resource(resource)] = resource
        return tmp_cache

    def list(self):
        """
        Returns the cached values
        """
        self._cache_resources()
        return self._cache.values()

    def _id_for_resource(self, resource):
        raise NotImplementedError()

    def _get_resources(self):
        raise NotImplementedError()


class GreenTimeLivedCache(TimeLivedCache):
    """
    Extend the TimeLivedCache to use green thread.
    """
    def __init__(self, ttl=DEFAULT_TTL):
        super(GreenTimeLivedCache, self).__init__(ttl)
        # Replace with the semaphore.
        self._lock = Semaphore()


class VolumeCache(GreenTimeLivedCache):
    """
    Caches the volumes
    """
    def __init__(self, driver, ttl=DEFAULT_TTL):
        assert driver
        self._driver = driver
        super(VolumeCache, self).__init__(ttl)

    def _get_resources(self):
        return self._driver.cache_volume_data()

    def _get_cache(self):
        return self._get_resources()

    def set_by_id(self, pvc_id, local_id):
        with self._lock:
            self._cache[pvc_id] = local_id

    def get_by_id(self, pvc_id, default=None):
        self._cache_resources()
        if (len(self._cache) != 0):
            if pvc_id in self._cache:
                LOG.info(_("Found volume id equals: '%s'" % pvc_id))
                return self._cache[pvc_id]
        LOG.info(_("No volume found which equals: '%s'" % pvc_id))
        return default


class SCGCache(GreenTimeLivedCache):
    """
    Caches the SCGs.
    """
    def __init__(self, nova, ttl=DEFAULT_TTL):
        assert nova
        self._nova = nova
        super(SCGCache, self).__init__(ttl)

    def __str__(self):
        return _("Storage Connectivity Group Cache")

    def _id_for_resource(self, resource):
        return resource.display_name

    def _get_resources(self):
        """
        Calls the api to get all SCGs
        """
        return self._nova.storage_connectivity_groups.list(detailed=True)

    def by_name(self, name, default=None):
        """
        Returns the SCG by name
        """
        self._cache_resources()
        if (len(self._cache) != 0):
            if name in self._cache:
                LOG.info(_("Found scg which name equals: '%s'" % name))
                return self._cache[name]
        LOG.info(_("No scg found which equals name: '%s'" % name))
        return default

    def by_id(self, scg_id, default=None):
        """
        Returns the SCG by id
        """
        self._cache_resources()
        if (len(self._cache) != 0):
            for scg in self.list():
                if scg.id == scg_id:
                    LOG.info(_("Found scg which equals id: '%s'" % scg_id))
                    return scg
        LOG.info(_("No scg found which equals id: '%s'" % scg_id))
        return default

__lock = threading.Lock()
__utils = None


def get_utils():
    """
    Returns a singleton Utils object
    """
    global __lock
    global __utils
    if __utils is not None:
        return __utils
    with __lock:
        if __utils is not None:
            return __utils
        __utils = Utils()
    return __utils


class Utils(object):
    """
    This Utils class leverages the pvcnovaclient and pvccinderclient
    to retrieve the Storage Connectivity Group, Storage Providers and
    Storage Templates information, etc.

    Usage sample:
        username = 'root'
        password = 'passw0rd'
        tenant = 'ibm-default'
        auth_url = 'https://z3-9-5-127-193.rch.nimbus.kstart.ibm.com/\
        powervc/openstack/admin/v3'
        cacert = '/home/osadmin/z3-9-5-127-193.rch.nimbus.kstart.ibm.com'

        utils = utils.Utils(username=username,
                                api_key=password,
                                project_id=tenant,
                                auth_url=auth_url,
                                insecure=False,
                                cacert=cacert)
        sps = utils.get_scg_accessible_storage_providers()
        sts = utils.get_scg_accessible_storage_templates()
        volumes = utils.get_scg_accessible_volumes()
    """
    def __init__(self):
        factory = importutils.import_module('powervc.common.client.factory')
        self._novaclient = factory.POWERVC.new_client(
            str(constants.SERVICE_TYPES.compute))
        self._cinderclient = factory.POWERVC.new_client(
            str(constants.SERVICE_TYPES.volume))
        self._localkeystoneclient = factory.LOCAL.new_client(
            str(constants.SERVICE_TYPES.identity))
        self.scg_cache = self.get_scg_cache(self._novaclient)

    def get_scg_cache(self, novaclient):
        """
        Return the SCGCache object.
        """
        return SCGCache(novaclient)

    def get_all_scgs(self):
        """
        Get all Storage Connectivity Groups from PowerVC

        :returns: A list of all Storage Connectivity Groups on PowerVC
        """
        return self.scg_cache.list()

    def get_our_scg_list(self):
        """
        If SCG names are specified in our configuration, see if the scgs exist.
        If they do not exist, raise an exception. If they exist, return the scg
        list for the name specified. If no SCG name is specified, return
        [] for the scg list.

        :returns: The StorageConnectivityGroup object list if found, else []
        :raise StorageConnectivityGroupNotFound: if the Storage Connectivity
        Groups could not be found on PowerVC
        """
        our_scg_list = []
        scg_to_use_list = CONF['powervc'].storage_connectivity_group
        for scg_to_use in scg_to_use_list:
            if scg_to_use:
                scg = self.scg_cache.by_name(scg_to_use)
                if scg is not None:
                    LOG.debug(_('PowerVC Storage Connectivity Group \'%s\' '
                                'found.'), scg.display_name)
                    our_scg = scg
                    our_scg_list.append(our_scg)
                else:
                    # If a SCG is specified and it's not found on the PowerVC,
                    # raise an exception.
                    LOG.error(_('The PowerVC Storage Connectivity Group'
                                ' \'%s\' was not found.'), scg_to_use)
                    raise StorageConnectivityGroupNotFound(scg=scg_to_use)
            else:
                LOG.error(_('No Storage Connectivity Group is specified in '
                            'the configuration settings.'))
        return our_scg_list

    def validate_scgs(self):
        """
        Validate the SCG name specified in the configuration,
        Return validated SCG list if successful
        Return [] if SCGs are not specified in the configuration file OR
        SCG specified is not found in PowerVC.
        """
        validated_scgs = []
        try:
            validated_scgs = self.get_our_scg_list()
        except StorageConnectivityGroupNotFound:
            return []
        return validated_scgs

    def get_scg_by_scgName(self, scg_name):
        """
        Get the SCG by scgName
        """
        return self.scg_cache.by_name(scg_name)

    def get_scg_by_scgUUID(self, scg_uuid):
        """
        Get the SCG by uuid
        """
        return self.scg_cache.by_id(scg_uuid)

    def get_scg_id_by_scgName(self, scg_name):
        """
        Get the SCG_ID by scg_name
        """
        if scg_name == "":
            return ""
        # If no scg_name is found, None is returned.
        scg = self.get_scg_by_scgName(scg_name)
        if scg is not None:
            return scg.id
        return ""

    def get_multi_scg_accessible_servers(self, scg_uuid_list, scg_name_list,
                                         detailed=True, search_opts=None):
        """
        Get accessible virtual servers by specified SCG UUID list
        or SCG Name list,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        If none of SCG UUID and Name specified, get all servers
        """
        class WrapServer():
            def __init__(self, server):
                self.server = server

            def __eq__(self, other):
                if isinstance(other, WrapServer):
                    return self.server.id == other.server.id
                else:
                    return False

            def __hash__(self):
                return hash(self.server.id)

        wrap_servers = set()
        if scg_uuid_list:
            for scg_uuid in scg_uuid_list:
                scg_servers = self.get_scg_accessible_servers(scg_uuid,
                                                              None,
                                                              detailed,
                                                              search_opts)
                wrap_scg_servers = [WrapServer(scg_server)
                                    for scg_server in scg_servers]
                wrap_servers.update(wrap_scg_servers)
            return [wrap_server.server for wrap_server in wrap_servers]

        if not scg_name_list:
            scg_name_list = CONF.powervc.storage_connectivity_group

        if scg_name_list:
            for scg_name in scg_name_list:
                scg_servers = self.get_scg_accessible_servers(None,
                                                              scg_name,
                                                              detailed,
                                                              search_opts)
                wrap_scg_servers = [WrapServer(scg_server)
                                    for scg_server in scg_servers]
                wrap_servers.update(wrap_scg_servers)
            return [wrap_server.server for wrap_server in wrap_servers]

    def get_scg_accessible_servers(self, scgUUID=None, scgName=None,
                                   detailed=True, search_opts=None):
        """
        Get accessible virtual servers by specified SCG UUID or scgName,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        If none of SCG UUID and Name specified, get all servers
        """
        scg = None
        # If no scgUUID specified.
        if not scgUUID:
            if scgName:
                # If scgName specified, then search by scgName
                scg = self.get_scg_by_scgName(scgName)
            else:
                # If scgName not specified, return None
                scg = None
        else:
            LOG.debug("Specified scgUUID: '%s'" % scgUUID)
            # retrieve scg by scgUUID
            scg = self.scg_cache.by_id(scgUUID)

        if not scg:
            # If no scg, then it's a IVM based PowerVC,
            # return all servers
            return self._novaclient.manager.list_all_servers(
                detailed, search_opts)

        # accessible_storage_servers to return
        accessible_storage_servers = []
        all_servers = self._novaclient.manager.list_all_servers(
            detailed, search_opts)

        # Filter the servers for the SCG
        for server in all_servers:
            server_scg = getattr(server, 'storage_connectivity_group_id', None)
            if server_scg and server_scg == scg.id:
                accessible_storage_servers.append(server)
            elif server_scg is None:
                # onboarding VMs
                accessible_storage_servers.append(server)

        LOG.info("All accessible_storage_servers: %s" %
                 accessible_storage_servers)

        return accessible_storage_servers

    def get_multi_scg_accessible_storage_providers(self,
                                                   scg_uuid_list,
                                                   scg_name_list,
                                                   detailed=True,
                                                   search_opts=None):
        """
        Get accessible storage providers by specified SCG UUID list
        or SCG Name list,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        """
        class WrapProvider():
            def __init__(self, provider):
                self.provider = provider

            def __eq__(self, other):
                if isinstance(other, WrapProvider):
                    return self.provider.id == other.provider.id
                else:
                    return False

            def __hash__(self):
                return hash(self.provider.id)

        wrap_providers = set()
        if scg_uuid_list:
            for scg_uuid in scg_uuid_list:
                scg_providers = self.get_scg_accessible_storage_providers(
                    scg_uuid, None, detailed, search_opts)
                wrap_scg_providers = [WrapProvider(scg_provider)
                                      for scg_provider in scg_providers]
                wrap_providers.update(wrap_scg_providers)
            return [wrap_provider.provider for wrap_provider in wrap_providers]

        if not scg_name_list:
            scg_name_list = CONF.powervc.storage_connectivity_group

        if scg_name_list:
            for scg_name in scg_name_list:
                scg_providers = self.get_scg_accessible_storage_providers(
                    None, scg_name, detailed, search_opts)
                wrap_scg_providers = [WrapProvider(scg_provider)
                                      for scg_provider in scg_providers]
                wrap_providers.update(wrap_scg_providers)
            return [wrap_provider.provider for wrap_provider in wrap_providers]

    def get_scg_accessible_storage_providers(self, scgUUID=None, scgName=None,
                                             detailed=True, search_opts=None):
        """
        Get accessible storage providers by specified SCG UUID or scgName,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        If none of SCG UUID and Name specified, get the first SCG from powerVC
        """
        scg = None
        # If no scgUUID specified.
        if not scgUUID:
            if scgName:
                # If scgName specified, then search by scgName
                scg = self.get_scg_by_scgName(scgName)
            else:
                # If scgName not specified, return None
                scg = None
        else:
            LOG.debug(_("Specified scgUUID: '%s'" % scgUUID))
            # retrieve scg by scgUUID
            scg = self.scg_cache.by_id(scgUUID)

        if not scg:
            # If no scg, then it's a IVM based PowerVC,
            # return all storage providers
            return (self._cinderclient.storage_providers.
                    list_all_providers(detailed, search_opts))

        # accessible_storage_providers to return
        accessible_storage_providers = []

        # retrieve fc_storage_access
        fc_storage_access = getattr(scg, 'fc_storage_access', False) or False
        LOG.info(_("scg['fc_storage_access']: '%s'" % fc_storage_access))

        # retrieve provider_id in vios_cluster
        provider_id = None
        vios_cluster = getattr(scg, 'vios_cluster', {})
        if vios_cluster:
            provider_id = vios_cluster.get('provider_id', '')
        LOG.info(_("scg['vios_cluster']['provider_id']: '%s'" %
                   (provider_id)))

        # retrieve all the storage-providers
        storage_providers = (self._cinderclient.storage_providers.
                             list_all_providers(detailed, search_opts))
        LOG.info(_("storage_providers: %s" % storage_providers))
        # Loop over the storage providers, if the 'storage_hostname' matches
        # SCG['vios_cluster']['provider_id'], or if SCG['fc_storage_access']
        # is "True" AND the provider's storage_type is "fc", then add to list
        for storage_provider in storage_providers:
            storage_hostname = getattr(storage_provider,
                                       'storage_hostname', '')
            storage_type = getattr(storage_provider,
                                   'storage_type', '')
            LOG.info(_("storage_provider['storage_hostname']: '%s'" %
                       (storage_hostname)))
            if storage_hostname and storage_hostname == provider_id:
                LOG.info(_("Add to accessible_storage_providers: %s" %
                           (storage_provider)))
                accessible_storage_providers.append(storage_provider)
            elif fc_storage_access and (constants.SCG_SUPPORTED_STORAGE_TYPE ==
                                        storage_type):
                LOG.info(_("Add to accessible_storage_providers: %s" %
                           (storage_provider)))
                accessible_storage_providers.append(storage_provider)
            # TODO as currently provider_id and storage_type are not
            # implemented
            else:
                accessible_storage_providers.append(storage_provider)

        LOG.info(_("All accessible_storage_providers: %s" %
                   (accessible_storage_providers)))

        return accessible_storage_providers

    def get_multi_scg_accessible_storage_templates(self,
                                                   scg_uuid_list,
                                                   scg_name_list):
        """
        Get accessible storage templates by specified SCG UUID list
        or SCG Name list,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        """
        class WrapType():
            def __init__(self, volume_type):
                self.type = volume_type

            def __eq__(self, other):
                if isinstance(other, WrapType):
                    return self.type.id == other.type.id
                else:
                    return False

            def __hash__(self):
                return hash(self.type.id)

        wrap_types = set()
        if scg_uuid_list:
            for scg_uuid in scg_uuid_list:
                scg_types = self.get_scg_accessible_storage_templates(
                    scg_uuid, None)
                wrap_scg_types = [WrapType(scg_type) for scg_type in scg_types]
                wrap_types.update(wrap_scg_types)
            return [wrap_type.type for wrap_type in wrap_types]

        if not scg_name_list:
            scg_name_list = CONF.powervc.storage_connectivity_group

        if scg_name_list:
            for scg_name in scg_name_list:
                scg_types = self.get_scg_accessible_storage_templates(
                    None, scg_name)
                wrap_scg_types = [WrapType(scg_type) for scg_type in scg_types]
                wrap_types.update(wrap_scg_types)
            return [wrap_type.type for wrap_type in wrap_types]

    def get_scg_accessible_storage_templates(self, scgUUID=None, scgName=None):
        """
        Get accessible storage templates by specified SCG UUID or scgName,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        If none of SCG UUID and Name specified, get the first SCG from powerVC
        """
        scg = None
        # If no scgUUID specified.
        if not scgUUID:
            if scgName:
                # If scgName specified, then search by scgName
                scg = self.get_scg_by_scgName(scgName)
            else:
                # If scgName not specified, get the SCG from the value
                # configured in powervc.conf
                scg = self.get_configured_scg()
        else:
            LOG.debug(_("Specified scgUUID: '%s'" % scgUUID))
            # retrieve scg by scgUUID
            scg = self.scg_cache.by_id(scgUUID)
        if not scg:
            # If no scg, then it's a IVM based PowerVC,
            # return all volumes
            return (self._cinderclient.volume_types.
                    list_all_storage_templates())

        # accessible_storage_templates to return
        accessible_storage_templates = []
        # filter out all the accessible storage template uuid
        volume_types = scg.list_all_volume_types()
        volume_type_ids = []
        for vol_type in volume_types:
            volume_type_ids.append(vol_type.__dict__.get("id"))
        all_volume_types = \
            self._cinderclient.volume_types.list_all_storage_templates()
        for storage_template in all_volume_types:
            if(storage_template.__dict__.get("id") in volume_type_ids):
                accessible_storage_templates.append(storage_template)

        LOG.info(_('accessible_storage_templates: %s' %
                   (accessible_storage_templates)))
        return accessible_storage_templates

    def get_multi_scg_accessible_volumes(self,
                                         scg_uuid_list,
                                         scg_name_list,
                                         detailed=True,
                                         search_opts=None):
        """
        Get accessible storage providers by specified SCG UUID list
        or SCG Name list,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        """
        class WrapVolume():
            def __init__(self, volume):
                self.volume = volume

            def __eq__(self, other):
                if isinstance(other, WrapVolume):
                    return self.volume.id == other.volume.id
                else:
                    return False

            def __hash__(self):
                return hash(self.volume.id)

        wrap_volumes = set()
        if scg_uuid_list:
            for scg_uuid in scg_uuid_list:
                scg_volumes = self.get_scg_accessible_volumes(scg_uuid,
                                                              None,
                                                              detailed,
                                                              search_opts)
                wrap_scg_volumes = [WrapVolume(scg_volume)
                                    for scg_volume in scg_volumes]
                wrap_volumes.update(wrap_scg_volumes)
            return [wrap_volume.volume for wrap_volume in wrap_volumes]

        if not scg_name_list:
            scg_name_list = CONF.powervc.storage_connectivity_group

        if scg_name_list:
            for scg_name in scg_name_list:
                scg_volumes = self.get_scg_accessible_volumes(None,
                                                              scg_name,
                                                              detailed,
                                                              search_opts)
                wrap_scg_volumes = [WrapVolume(scg_volume)
                                    for scg_volume in scg_volumes]
                wrap_volumes.update(wrap_scg_volumes)
            return [wrap_volume.volume for wrap_volume in wrap_volumes]

    def get_scg_accessible_volumes(self, scgUUID=None, scgName=None,
                                   detailed=True, search_opts=None):
        """
        Get SCG accessible volumes providers by specified SCG UUID or scgName,
        If both SCG UUID and SCG Name are specified specified, UUID is prior,
        If none of SCG UUID and Name specified, get the first SCG from powerVC
        """
        scg = None
        # If no scgUUID specified.
        if not scgUUID:
            if scgName:
                # If scgName specified, then search by scgName
                scg = self.get_scg_by_scgName(scgName)
            else:
                # If scgName not specified, get the SCG from the value
                # configured in powervc.conf
                scg = self.get_configured_scg()
        else:
            LOG.debug(_("Specified scgUUID: '%s'" % scgUUID))
            # retrieve scg by scgUUID
            scg = self.scg_cache.by_id(scgUUID)
        if not scg:
            # If no scg, then it's a IVM based PowerVC,
            # return all volumes
            return (self._cinderclient.volumes.list_all_volumes())

        # accessible_storage_volumes to return
        accessible_storage_volumes = []
        volumes = scg.list_all_volumes()
        volume_ids = []
        for vol in volumes:
            volume_ids.append(vol.__dict__.get("id"))
        all_volumes = \
            self._cinderclient.volumes.list_all_volumes(detailed, search_opts)
        for storage_volume in all_volumes:
            if(storage_volume.__dict__.get("id") in volume_ids):
                metadata = storage_volume.__dict__.get("metadata")
                if(metadata is not None):
                    is_boot_volume = metadata.get("is_boot_volume")
                    # Filter out the boot volumes
                    if(is_boot_volume != "True"):
                        accessible_storage_volumes.append(storage_volume)
                else:
                    accessible_storage_volumes.append(storage_volume)

        LOG.info(_('accessible_storage_volumes: %s' % (
                 accessible_storage_volumes)))
        return accessible_storage_volumes

    """ Zhao Jian """
    def get_image_scgs(self, imageUUID, details=False):
        """
        Get the Storage Connectivity Groups for the specified image.

        :param: imageUUID The UUID of the image
        :param: details To determine if SCG detail info needed
        :returns: The Storage Connectivity Groups for the specified image or an
                    empty list if none are found.
        """
        if imageUUID is not None:
            return self._novaclient.storage_connectivity_groups.list_for_image(
                imageUUID, details)
        else:
            return []

    def get_scg_image_ids(self, scgUUID):
        """
        Get the SCGImage identifiers for the specified Storage Connectivity
        Group.

        :param: scgUUID The UUID of the StorageConnectvityGroup
        :returns: The list of SCGImage identifiers for the specified Storage
                    Connectivity Group or an empty list if none are found.
        """
        if scgUUID is not None:
            return self._novaclient.scg_images.list_ids(scgUUID)
        else:
            return []

    def get_local_staging_project_id(self):
        """
        Get the local hosting OS staging project Id. If a staging
        project name is not found, a exception.StagingProjectNotFound
        exception will be raised. If no staging project is specified in
        the conf, the default value will be used as specified in constants.

        :returns: The local hosting OS staging project Id
        """
        ks_client = self._localkeystoneclient
        stagingname = CONF.powervc.staging_project_name or \
            constants.DEFAULT_STAGING_PROJECT_NAME
        try:
            projects = []
            if hasattr(ks_client, 'tenants'):
                # For keystone V2
                projects = ks_client.tenants.list()
            elif hasattr(ks_client, 'projects'):
                # For keystone V3
                projects = ks_client.projects.list()
            for tenant in projects:
                projectname = tenant.name
                projectid = tenant.id
                if projectname == stagingname:
                    LOG.debug(_('The staging_project_name %s has id %s'),
                              stagingname, projectid)
                    return projectid
        except Exception as e:
            LOG.debug(_('An error occurred getting the tenant list: %s.'), e)
        LOG.debug(_('Unable to find staging project: %s'), stagingname)
        raise exception.StagingProjectNotFound(name=stagingname)

    def get_local_staging_user_id(self):
        """
        Get the local hosting OS staging user Id which defaults to
        constants.DEFAULT_STAGING_USERNAME if not set in the conf.
        If a staging user name is not found, a StagingUserNotFound
        exception will be raised.

        :returns: The local hosting OS staging user Id
        """
        ks_client = self._localkeystoneclient
        staginguser = CONF.powervc.staging_user or \
            constants.DEFAULT_STAGING_USER_NAME
        try:
            for user in ks_client.users.list():
                username = user.name
                userid = user.id
                if staginguser == username:
                    LOG.debug(_('The staging_user %s has id %s'),
                              staginguser, userid)
                    return userid
        except Exception as e:
            LOG.debug(_('An error occurred getting the user list: %s'), e)
        LOG.debug(_('Unable to find staging user: %s'), staginguser)
        raise exception.StagingUserNotFound(name=staginguser)

    """ Zhao Jian """
    def filter_out_available_scgs(self, available_powervc_scgs):
        """
        Filter out an available scg list for user to use. An available scg must
         be both in the scg list that get from CONF file and in the scg list
        that get from PowerVC

        :param: available_powervc_scgs: Specific SCG list from PowerVC
        :returns: The available SCG object list if found , else []
        """
        available_scg_list = []
        scg_to_use_list = CONF['powervc'].storage_connectivity_group
        for scg in available_powervc_scgs:
            if scg is not None and scg.display_name in scg_to_use_list.keys():
                LOG.debug(_('PowerVC Storage Connectivity Group \'%s\' '
                            'found.'), scg.display_name)
                available_scg = scg
                available_scg_list.append(available_scg)
        return available_scg_list

    def get_hypervisor_by_name(self, hostname):
        """
        Get the information for the specific hypervisor with the given hostname

        :param: hostname
        :return: the specific hypervisor information
        """
        if hostname is None:
            return None
        hypervisor_list = self._novaclient.hypervisors.list()
        specific_hypervisor = None
        for hypervisor in hypervisor_list:
            if hypervisor._info['service']['host'] == hostname:
                specific_hypervisor = hypervisor
                break
        return specific_hypervisor


def import_relative_module(relative_import_str, import_str):
    """
    Imports a module relative to another. Can be used when more
    than 1 module of the given name exists in the python path
    to resolve any discrepency in multiple paths.

    :param relative_import_str: a module import string which
    neighbors the actual import. for example 'glanceclient'.
    :param import_str: the module import string. for example
    'tests.utils'

    example:
    utils = import_relative_module('glanceclient', 'tests.utils')
    fapi = utils.FakeAPI(...)
    """
    mod = importutils.import_module(relative_import_str)
    mpath = os.path.dirname(os.path.dirname(os.path.realpath(mod.__file__)))
    if not sys.path[0] is mpath:
        sys.path.insert(0, mpath)
    return importutils.import_module(import_str)


class StagingCache(object):
    """
    Provides a lazy cache around the local staging user and project.
    Consumers can use the staging_user_and_project property to retrieve the
    (user_id, project_id) pair for the staging user. These values are
    lazily fetched at most once
    """

    def __init__(self):
        super(StagingCache, self).__init__()
        self.utils = get_utils()
        self.staging_user = None
        self.staging_project = None

    @property
    def is_valid(self):
        uid, pid = self.get_staging_user_and_project()
        return uid is not None and pid is not None

    def get_staging_user_and_project(self, raise_on_invalid=False):
        try:
            if not self.staging_user:
                self.staging_user = self.utils.get_local_staging_user_id()
            if not self.staging_project:
                self.staging_project = \
                    self.utils.get_local_staging_project_id()
            return (self.staging_user, self.staging_project)
        except exception.StagingProjectNotFound as e:
            if raise_on_invalid:
                raise e
            return (None, None)
        except exception.StagingUserNotFound as e:
            if raise_on_invalid:
                raise e
            return (None, None)
