# Copyright 2013 IBM Corp.

import six
import urllib
from novaclient import base as client_base
from novaclient.v1_1 import servers
from novaclient.v1_1 import hypervisors
from novaclient.v1_1 import images
from novaclient.v1_1 import flavors
from novaclient.v1_1 import volumes
from novaclient.v1_1.volume_types import VolumeType
from powervc.common.client.extensions import base
from powervc.common import utils
import logging

LOG = logging.getLogger(__name__)


class Client(base.ClientExtension):

    def __init__(self, client):
        super(Client, self).__init__(client)
        self.manager = PVCServerManager(client)
        self.servers = servers
        self.hypervisors = hypervisors.HypervisorManager(client)
        self.images = images.ImageManager(client)
        self.flavors = flavors.FlavorManager(client)
        self.storage_connectivity_groups = \
            StorageConnectivityGroupManager(client)
        self.volumes = volumes.VolumeManager(client)
        self.scg_images = SCGImageManager(client)
    # any extensions to std nova client go below


class PVCServerManager(servers.ServerManager):
    """
    This ServerManager class is specific for PowerVC booting a VM.
    As the PowerVC boot API does not follow the standard openstack boot API,
    need to rewrite the default boot method to satisfy powerVC boot restAPI
    content.
    """

    def list(self, detailed=True, search_opts=None,
             scgUUID=None,
             scgName=None):
        """
        Get a list of the Servers that filtered by a specified SCG UUID
        or SCG name, if both SCG UUID and SCG name are specified, UUID has the
        high priority to check.

        :rtype: list of :class:`Server`
        """
        if scgUUID or scgName:
            return utils.get_utils().get_scg_accessible_servers(scgUUID,
                                                                scgName,
                                                                detailed,
                                                                search_opts
                                                                )
        else:
            # This will get all scgs accessible servers
            return utils.get_utils().\
                get_multi_scg_accessible_servers(None,
                                                 None,
                                                 detailed,
                                                 search_opts
                                                 )

    def list_all_servers(self, detailed=True, search_opts=None):
        """
        Get a list of all servers without filters.
        Optional detailed returns details server info.
        Optional reservation_id only returns instances with that
        reservation_id.

        :rtype: list of :class:`Server`
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
        return self._list("/servers%s%s" % (detail, query_string), "servers")

    # This function was copied from (/usr/lib/python2.6/site-packages/
    # novaclient/v1_1/servers.py) before, but changes needed when activation
    # data contains userdata and files, because in a boot action, local OS
    # novaclient's _boot will read them from CLI or GUI firstly, then when our
    # driver is triggered, this version of _boot should just forward the data
    # or file content to PowerVC without any reading, otherwise error happens.
    # RTC/172018, add support to boot server with activation data.
    def _boot(self, resource_url, response_key, name, image, flavor,
              meta=None, files=None, userdata=None, reservation_id=None,
              return_raw=False, min_count=None, max_count=None,
              security_groups=None, key_name=None, availability_zone=None,
              block_device_mapping=None, nics=None, scheduler_hints=None,
              config_drive=None, admin_pass=None, **kwargs):
        """Create (boot) a new server.

        :param name: Server Name.
        :param image: The string of PowerVC `Image` UUID to boot with.
        :param flavor: The :dict of `Flavor` that need to boot onto.
        :param meta: A dict of arbitrary key/value metadata to store for this
                     server. A maximum of five entries is allowed, and both
                     keys and values must be 255 characters or less.
        :param files: A dict of files to overrwrite on the server upon boot.
                      Keys are file names (i.e. ``/etc/passwd``) and values
                      are the file contents (either as a string or as a
                      file-like object). A maximum of five entries is allowed,
                      and each file must be 10k or less.
        :param userdata: user data to pass to make config drive this can be a
                      file type object as well or a string. PowerVC don't use
                      metadata server for security considerations.
        :param reservation_id: a UUID for the set of servers being requested.
        :param return_raw: If True, don't try to coearse the result into
                           a Resource object.
        :param security_groups: list of security group names
        :param key_name: (optional extension) name of keypair to inject into
                         the instance
        :param availability_zone: Name of the availability zone for instance
                                  placement.
        :param block_device_mapping: A dict of block device mappings for this
                                     server.
        :param nics:  (optional extension) an ordered list of nics to be
                      added to this server, with information about
                      connected networks, fixed ips, etc.
        :param scheduler_hints: (optional extension) arbitrary key-value pairs
                              specified by the client to help boot an instance.
        :param config_drive: (optional extension) value for config drive
                            either boolean, or volume-id
        :param admin_pass: admin password for the server.
        """
        body = {"server": {
            "name": name,
            "imageRef": image,
            "flavor": {},
        }}

        # Add the flavor information to PowerVC for booting VM
        body["server"]["flavor"]['ram'] = flavor['memory_mb']
        body["server"]["flavor"]['vcpus'] = flavor['vcpus']
        body["server"]["flavor"]['disk'] = flavor['root_gb']
        body["server"]["flavor"]['OS-FLV-EXT-DATA:ephemeral'] = \
            flavor.get('OS-FLV-EXT-DATA:ephemeral', 0)
        body["server"]["flavor"]['extra_specs'] = flavor['extra_specs']

        # If hypervisor ID specified:
        if kwargs.get("hypervisor", None):
            body["server"]['hypervisor_hostname'] = kwargs["hypervisor"]

        if userdata:
            # RTC/172018 -- start
            # comment out the following, already done by local OS nova client
            #    if hasattr(userdata, 'read'):
            #       userdata = userdata.read()

            #    userdata = strutils.safe_encode(userdata)
            #    body["server"]["user_data"] = base64.b64encode(userdata)
            body["server"]["user_data"] = userdata
        # RTC/172018 -- end
        if meta:
            body["server"]["metadata"] = meta
        if reservation_id:
            body["server"]["reservation_id"] = reservation_id
        if key_name:
            body["server"]["key_name"] = key_name
        if scheduler_hints:
            body['os:scheduler_hints'] = scheduler_hints
        if config_drive:
            body["server"]["config_drive"] = config_drive
        if admin_pass:
            body["server"]["adminPass"] = admin_pass
        if not min_count:
            min_count = 1
        if not max_count:
            max_count = min_count
        body["server"]["min_count"] = min_count
        body["server"]["max_count"] = max_count

        if security_groups:
            body["server"]["security_groups"] = ([{'name': sg}
                                                  for sg in security_groups])

        # Files are a slight bit tricky. They're passed in a "personality"
        # list to the POST. Each item is a dict giving a file name and the
        # base64-encoded contents of the file. We want to allow passing
        # either an open file *or* some contents as files here.

        if files:
            personality = body['server']['personality'] = []
            # RTC/172018 -- start
            # comment out the following, already done by local OS nova client
            # for filepath, file_or_string in files.items():
            #    if hasattr(file_or_string, 'read'):
            #        data = file_or_string.read()
            #    else:
            #        data = file_or_string

            for file in files:
                personality.append({
                    'path': file[0],
                    'contents': file[1].encode('base64'),
                })
            # RTC/172018 -- end

        if availability_zone:
            body["server"]["availability_zone"] = availability_zone

        # Block device mappings are passed as a list of dictionaries
        if block_device_mapping:
            bdm = body['server']['block_device_mapping'] = []
            for device_name, mapping in block_device_mapping.items():
                #
                # The mapping is in the format:
                # <id>:[<type>]:[<size(GB)>]:[<delete_on_terminate>]
                #
                bdm_dict = {'device_name': device_name}

                mapping_parts = mapping.split(':')
                id_ = mapping_parts[0]
                if len(mapping_parts) == 1:
                    bdm_dict['volume_id'] = id_
                if len(mapping_parts) > 1:
                    type_ = mapping_parts[1]
                    if type_.startswith('snap'):
                        bdm_dict['snapshot_id'] = id_
                    else:
                        bdm_dict['volume_id'] = id_
                if len(mapping_parts) > 2:
                    bdm_dict['volume_size'] = mapping_parts[2]
                if len(mapping_parts) > 3:
                    bdm_dict['delete_on_termination'] = mapping_parts[3]
                bdm.append(bdm_dict)

        if nics is not None:
            # NOTE(tr3buchet): nics can be an empty list
            all_net_data = []
            for nic_info in nics:
                net_data = {}
                # if value is empty string, do not send value in body
                if nic_info.get('net-id'):
                    net_data['uuid'] = nic_info['net-id']
                if nic_info.get('v4-fixed-ip'):
                    net_data['fixed_ip'] = nic_info['v4-fixed-ip']
                if nic_info.get('port-id'):
                    net_data['port'] = nic_info['port-id']
                all_net_data.append(net_data)
            body['server']['networks'] = all_net_data

        return self._create(resource_url, body, response_key,
                            return_raw=return_raw, **kwargs)

    def _resize_pvc(self, server, info, **kwargs):
        """
        This method is used to overwrite the resize in the
        class ServerManager
        """
        return self._action('resize', server, info=info, **kwargs)

    def list_instance_storage_viable_hosts(self, server):
        """
        Get a list of hosts compatible with this server.
        Used for getting candidate host hypervisors from powervc for
        live migration. We need to do things a bit different
        since there not a common schema apperently for the content
        returned. See below..

            {
               "8233E8B_100008P":{
                  "host":"8233E8B_100008P"
               },
               "8233E8B_100043P":{
                  "host":"8233E8B_100043P"
               }
            }

        :param server: ID of the :class:`Server` to get.
        :rtype: dict
        """
        url = "/storage-viable-hosts?instance_uuid=%s"\
            % (client_base.getid(server))

        _resp, body = self.api.client.get(url)
        return body


class StorageConnectivityGroup(client_base.Resource):
    """
    Entity class for StorageConnectivityGroup
    """
    def __repr__(self):
        return ("<StorageConnectivityGroup: %s, displayname: %s>" %
                (self.id, self.display_name))

    def list_all_volumes(self):
        """
        Get a list of accessible volume for this SCG.

        :rtype: list of :class:`Volume`
        """
        return self.manager.list_all_volumes(self.id)

    def list_all_volume_types(self):
        """
        Get a list of accessible volume types for this SCG.

        :rtype: list of :class:`VolumeType`
        """
        return self.manager.list_all_volume_types(self.id)


class StorageConnectivityGroupManager(client_base.Manager):
    """
    Manager class for StorageConnectivityGroup
    Currently get and list functions for StorageConnectivityGroup
    are implemented.
    """
    resource_class = StorageConnectivityGroup

    def get(self, scgUUID):
        """
        Get a StorageConnectivityGroup.

        :param server: UUID `StorageConnectivityGroup` to get.
        :rtype: :class:`Server`
        """
        try:
            return self._get("/storage-connectivity-groups/%s" % scgUUID,
                             "storage_connectivity_group")
        except Exception as e:
            # If PowerVC Express installations in IVM mode
            # would receive BadRequest
            LOG.error('A problem was encountered while getting the '
                      ' Storage Connectivity Group %s: %s '
                      % (scgUUID, str(e)))
            return None

    def list_for_image(self, imageUUID):
        """
        Get a list of StorageConnectivityGroups for the specified image. If
        an error occurs getting the SCGs for an image, an exception is logged
        and raised.

        :param: imageUUID The image UUID:
        :rtype: list of :class:`StorageConnectivityGroup`
        """
        try:
            return self._list("/images/%s/storage-connectivity-groups" %
                              imageUUID, "storage_connectivity_groups")
        except Exception as e:
            LOG.error('A problem was encountered while getting a list of '
                      'Storage Connectivity Groups for image %s: %s '
                      % (imageUUID, str(e)))
            raise e

    def list_all_volumes(self, scgUUID):
        """
        Get a list of accessible volume for this SCG.

        :rtype: list of :class:`Volume`
        """
        try:
            return self._list("/storage-connectivity-groups/%s/volumes"
                              % scgUUID, "volumes", volumes.Volume)
        except Exception as e:
            LOG.error('A problem was encountered while getting a list of '
                      'accessible volumes for scg %s: %s '
                      % (scgUUID, str(e)))
            raise e

    def list_all_volume_types(self, scgUUID):
        """
        Get a list of accessible volume types for this SCG.

        :rtype: list of :class:`VolumeType`
        """
        try:
            return self._list("/storage-connectivity-groups/%s/volume-types"
                              % scgUUID, "volume-types", VolumeType)
        except Exception as e:
            LOG.error('A problem was encountered while getting a list of '
                      'accessible volume types for scg %s: %s '
                      % (scgUUID, str(e)))
            raise e

    def list(self, detailed=True, search_opts=None):
        """
        Get a list of StorageConnectivityGroups.
        Optional detailed returns details StorageConnectivityGroup info.

        :rtype: list of :class:`StorageConnectivityGroup`
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
        try:
            return self._list("/storage-connectivity-groups%s%s" %
                              (detail, query_string),
                              "storage_connectivity_groups")
        except Exception as e:
            # If PowerVC Express installations in IVM mode
            # would receive BadRequest
            LOG.error('A problem was encountered while getting a list'
                      ' of Storage Connectivity Groups: %s '
                      % str(e))
            return []


class SCGImage(client_base.Resource):
    """
    Entity class for SCGImage
    """
    def __repr__(self):
        return ("<SCGImage: %s, name: %s>" %
                (self.id, self.name))


class SCGImageManager(client_base.Manager):
    """
    Manager class for SCGImage
    Currently the list function for SCGImages in a StorageConnectivityGroup,
    and the image identifiers of SCGImages in a StorageConnectivityGroup is
    implemented.
    """
    resource_class = SCGImage

    def list(self, scgUUID):
        """
        Get a list of SCGImages for the specified StorageConnectivityGroup. If
        an error occurs getting the SCGImages, and exception is logged and
        raised.

        :param: scgUUID The StorageConnectivityGroup UUID:
        :rtype: list of :class:`SCGImage`
        """
        try:
            return self._list("/storage-connectivity-groups/%s/images" %
                              scgUUID, "images")
        except Exception as e:
            LOG.error('A problem was encountered while getting a list of '
                      'images for Storage Connectivity Group \'%s\': %s '
                      % (scgUUID, str(e)))
            raise e

    def list_ids(self, scgUUID):
        """
        Get a list of SCGImage identifiers for the specified
        StorageConnectivityGroup. If an error occurs getting the SCGImage ids,
        and exception is logged and raised.

        :param: scgUUID The StorageConnectivityGroup UUID:
        :rtype: list of :class:`SCGImage` identifiers
        """
        ids = []
        SCGImages = self.list(scgUUID)
        if SCGImages:
            for image in SCGImages:
                ids.append(image.id)
        return ids
