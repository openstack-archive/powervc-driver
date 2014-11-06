# Copyright 2013, 2014 IBM Corp.

"""
Doing PowerVC initialize work, including image, instance sync.
"""

import math
import time
import sys
from socket import inet_aton
from eventlet import greenthread

import nova
import powervc.common.config as cfg
from nova import notifications
from nova import db
from nova import exception
from nova import manager
from nova import compute
from nova import conductor
from nova import network
from nova import block_device
from nova.db import api as db_api
from nova.image import glance
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
from oslo.utils import importutils
from nova.openstack.common import log as logging
from oslo.utils import timeutils
from nova.openstack.common import loopingcall
from nova.openstack.common.loopingcall import LoopingCallDone
from oslo.serialization import jsonutils
from nova import objects
from nova.objects import instance as instance_obj
from nova.objects import base as obj_base
from powervc.nova.driver.compute import computes
from powervc.nova.driver.compute import constants
from powervc.nova.driver.compute import task_states as pvc_task_states
from powervc.nova.driver.virt.powervc.sync import flavorsync
from powervc import utils
from powervc.common import utils as utills
from powervc.common.gettextutils import _
from powervc.common.client import delegate as ctx_delegate

from powervc.common import messaging

from oslo.messaging.notify import listener
from oslo.messaging import target
from oslo.messaging import transport

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class PowerVCCloudManager(manager.Manager):

    def __init__(self, compute_driver=None, *args, **kwargs):
        """
        Load configuration options and connect to PowerVC.

        :param compute_driver: the fully qualified name of the compute Driver
                               that will be used with this manager
        """
        super(PowerVCCloudManager, self).__init__(*args, **kwargs)

        # This needs to be defined in new .conf file.
        compute_driver = CONF.powervc.powervc_driver

        LOG.info(_("Loading compute driver '%s'") % compute_driver)

        try:
            self.driver = importutils.import_object_ns(
                'powervc.nova.driver.virt', compute_driver, None)
        except ImportError as e:
            LOG.error(_("Unable to load the PowerVC driver: %s") % (e))
            sys.exit(1)

        # Defer update local vm when powervc vm ids in spawning status
        self.defer_update_local_vm_in_spawning_ids = []
        # The variable used to cache the volume data
        self.cache_volume = utills.VolumeCache(self.driver)
        self.compute_api = compute.API()
        self.network_api = network.API()
        self.conductor_api = conductor.API()

        self._default_image = None

        # Have to import here instead of at the top, otherwise
        # there is no way to write UT for the manager.
        from powervc.common.client import factory as clients
        keystone = clients.LOCAL.keystone

        orig_ctx = nova.context.get_admin_context()
        orig_ctx.project_id = keystone.tenant_id
        orig_ctx.user_id = keystone.user_id

        ctx = ctx_delegate.context_dynamic_auth_token(orig_ctx, keystone)
        self.project_id = CONF.powervc.admin_tenant_name

        scg_list = utills.get_utils().validate_scgs()
        if not scg_list:
            LOG.error(_('Nova-powervc service terminated, Invalid Storage'
                        ' Connectivity Group specified.'))
            sys.exit(1)

        self.scg_id_list = [scg.id for scg in scg_list]

        self._staging_cache = utills.StagingCache()

        # Initialize the compute manager
        self.compute_manager = computes.ComputeServiceManager(self.driver,
                                                              scg_list)
        self.compute_manager.start()

        # Check if necessary services are ready.
        self._check_services(ctx)

        # Keep track of instances in need of a sync. Instances are 'marked'
        # as needing to be synced for various reasons such as being in an
        # unexpected state when we get a notification about the instance from
        # PowerVC. The keys are the PowerVC instance IDs, not the local
        # instance IDs.
        self.sync_instances = {}

        # Keep track of whether or not we need to sync all instances on the
        # next instance sync interval.
        self.full_instance_sync_required = False

        # Synchronize the public flavors from PowerVC
        flavorsync.FlavorSync(self.driver,
                              self.scg_id_list).synchronize_flavors(ctx)

        # Synchronize instances from PowerVC
        self._synchronize_instances(ctx)

        # Listen for out-of-band PowerVC changes
        self._create_powervc_listeners(ctx)

        # Listen for local changes, to update the correct
        # host/node/hostname information when we defer scheduling
        # to powerVC. Currently needed for live migration and resize.
        self._create_local_listeners(ctx)

        # Set up periodic polling to sync instances
        # and flavor sync.
        self._start_periodic_instance_flavor_sync(ctx)

    def _check_services(self, ctx):
        """
        Check if other necessary services are ready.
        """
        try:
            params = {}
            filters = {}
            filters['limit'] = CONF.powervc.image_limit
            params['filters'] = filters
            glance.get_default_image_service().detail(ctx, **params)
        except Exception, e:
            # Just give an error, so the user can start
            # the glance.
            # Don't exit, because the glance might be starting.
            LOG.error(_("Glance service is not ready. " + str(e)))

    def _synchronize_instances(self, ctx):
        """
        Called to synchronize instances on boot.
        Check instances fetched from PowerVC,
        if it is not in OpenStack, then insert it,
        if it is already in OpenStack, then update it.

        :param: ctx The security context
        """

        LOG.info(_("Initial instance sync. starts."))

        # Some counters to record instances modified.
        count_new_instances = 0
        count_updated_instances = 0
        count_deleted_instances = 0
        count_error = 0

        try:
            # Get both lists from local DB and PowerVC
            pvc_instances = self.driver.list_instances()
            local_instances = self._get_all_local_instances(ctx)
        except Exception, e:
            # No point to do any following step, if error happens above.
            count_error += 1
            pvc_instances = []
            local_instances = []
            LOG.error(_("Failed to setup a synchronization. " + str(e)))

        # Sync. from PowerVC ---> local nova DB,
        # to insert new instances and update existing instances
        LOG.info(_("Initial instance sync: pvc -> local"))
        for instance in pvc_instances:
            """
                A sample of returned instance from PowerVC:
                https://w3-connections.ibm.com/wikis/home?lang=en-us#!/
                wiki/We32ccda54f51_4ede_bfd6_8f9cc4b70d23/page/REST%20Responses
            """

            greenthread.sleep(0)

            # Convert an object to dictionary,
            # because some filed names has spaces.
            pvc_instance = instance.__dict__

            LOG.info(_("Processing PVC instance: %s") % pvc_instance['id'])

            matched_instances = self.\
                _get_local_instance_by_pvc_id(ctx, pvc_instance['id'])
            if len(matched_instances) == 0:
                # Not found, and insert into local DB
                try:
                    if self._add_local_instance(ctx, pvc_instance):
                        count_new_instances += 1
                except Exception, e:
                    count_error += 1
                    LOG.error(_("Insert a new PVC instance failed."
                                + str(pvc_instance)
                                + ", " + str(e)))
            else:
                # Found
                if len(matched_instances) > 1:
                    LOG.error(_("More than one instance in DB "
                                "match one PowerVC instance: "
                                + pvc_instance['id']))
                try:
                    if self._update_local_instance(ctx,
                                                   matched_instances[0],
                                                   pvc_instance):
                        count_updated_instances += 1
                except Exception, e:
                    count_error += 1
                    LOG.error(_("Update a PVC instance failed. "
                                + str(pvc_instance)
                                + ", " + str(e)))

        # Sync. from local nova DB ---> PowerVC,
        # to remove invalid instances that are not in pvc anymore.
        LOG.info(_("Initial instance sync: local -> pvc"))
        for local_instance in local_instances:

            greenthread.sleep(0)

            LOG.info(_("Processing local instance: %s") % local_instance['id'])

            if not self._is_valid_pvc_instance(ctx,
                                               local_instance,
                                               pvc_instances):
                try:
                    # If it is not valid in pvc, also delete form the local.
                    if self._remove_local_instance(ctx,
                                                   local_instance,
                                                   force_delete=True):
                        count_deleted_instances += 1
                except Exception, e:
                    count_error += 1
                    LOG.error(_("Delete a PVC instance failed. "
                                + str(local_instance)
                                + ", " + str(e)))

        LOG.info(_("""
                    *******************************
                    Initial instance sync. result:
                    [ %(insert)s inserted,
                      %(update)s updated,
                      %(delete)s deleted ]
                    Error: %(error)s
                    *******************************
                 """ %
                 {'insert': count_new_instances,
                  'update': count_updated_instances,
                  'delete': count_deleted_instances,
                  'error': count_error}))

    def _get_all_local_instances(self, context):
        """ Get all instances for a PowerVC."""
        filters = {'deleted': False, 'architecture': constants.PPC64}
        db_matches = db.instance_get_all_by_filters(context, filters)
        local_pvc_instances = []
        for local_instance in db_matches:
            if self._is_pvc_instance(context, local_instance):
                local_pvc_instances.append(local_instance)
        return local_pvc_instances

    def _get_local_instance_by_pvc_id(self, context, pvcid):
        """ Get a local instance by a PowerVC uuid."""
        filters = {'deleted': False, 'metadata': {constants.PVC_ID: pvcid}}
        db_matches = db.instance_get_all_by_filters(context, filters)
        return db_matches

    def _sync_existing_instance(self, context, local_instance, pvc_instance):
        """Update a local instance with a PowerVC instance."""

        base_options, unused_image, unused_flavor = \
            self._translate_pvc_instance(context, pvc_instance, local_instance)

        # In order to support the rename function in the Hosting OS, we will
        # avoid the name of the instance is updated.
        # In this situation, the name of the same instance will be different in
        # the hosting OS and PowerVC.
        base_options['display_name'] = local_instance.get('display_name')

        self.compute_api.update(context, local_instance, **base_options)
        self.sync_volume_attachment(context,
                                    pvc_instance['id'],
                                    local_instance)
        # Try to link network with instance if we haven't.
        self._fix_instance_nw_info(context, local_instance)

    def _translate_pvc_instance(self, ctx, pvc_instance, db_instance=None):
        """Map fields in a PowerVC instance to a local instance."""

        def epoch_to_date(seconds_since_epoch):
            """
            Converts a string or floating containing the number of seconds
            since the epoch, to a date object. If the given seconds are None
            the method returns an object with now().

            :returns: the date from the seconds or now
            """
            if not seconds_since_epoch:
                return timeutils.utcnow()

            try:
                # try directly parse by iso format time as PowerVC return
                # already formatted isotime. By issue 166750
                return timeutils.parse_isotime(seconds_since_epoch)
            except:
                # If failed to parse by iso format time, then parse by
                # seconds_since_epoch
                time_str = time.strftime(timeutils._ISO8601_TIME_FORMAT,
                                         time.gmtime(seconds_since_epoch))
                return timeutils.parse_strtime(
                    time_str, fmt=timeutils._ISO8601_TIME_FORMAT)

        image = self._get_image_from_instance(ctx, pvc_instance, db_instance)
        flavor = self._get_flavor_from_instance(ctx, pvc_instance, db_instance)

        # Use the instance properties from PowerVC to be accurate
        if pvc_instance.get('vcpus') is not None:
            vcpus = int(math.ceil(float(pvc_instance.get('vcpus'))))
        else:
            vcpus = flavor.get('vcpus')

        if pvc_instance.get('memory_mb') is not None:
            memory_mb = pvc_instance.get('memory_mb')
        else:
            memory_mb = flavor.get('memory_mb')

        if pvc_instance.get('root_gb') is not None:
            root_gb = pvc_instance.get('root_gb')
        else:
            root_gb = flavor.get('root_gb')

        if pvc_instance.get('ephemeral_gb') is not None:
            ephemeral_gb = pvc_instance.get('ephemeral_gb')
        else:
            ephemeral_gb = flavor.get('ephemeral_gb')

        # need to set the root_device_name for the volume attachment auto
        # assigned device name purpose
        root_device_name = self._get_instance_root_device_name(pvc_instance,
                                                               db_instance)

        address4 = pvc_instance['accessIPv4']
        # Has to be a valid IP, or null
        try:
            inet_aton(address4)
        except Exception:
            LOG.debug(_("null for addressIPv4"))
            address4 = None

        launched_at = epoch_to_date(pvc_instance.get('launched_at'))
        scheduled_at = epoch_to_date(pvc_instance.get('scheduled_at'))

        # We need to make sure hostname is a string
        hostname = pvc_instance['OS-EXT-SRV-ATTR:hypervisor_hostname']
        if hostname is None:
            hostname = ''

        if db_instance:
            # Get metadata from db_instance
            # If it is a dict, leave as it is
            # If it is a list, convert the list to dict
            metadata = db_instance.get('metadata', {})

            # Sometimes the instance's metadata will be a list
            # Convert the metadata list to metadata dict
            if isinstance(metadata, list):
                meta_dict = {}
                for entry in metadata:
                    key = entry.get('key', None)
                    value = entry.get('value', None)
                    if key and value:
                        meta_dict[key] = value
                metadata = meta_dict
        else:
            metadata = {}

        # Copy the powervc specified properties into metadata
        metadata = utils.fill_metadata_dict_by_pvc_instance(metadata,
                                                            pvc_instance)

        ins = {
            'image_ref': image['id'],
            'launch_time': launched_at,
            'launched_at': launched_at,
            'scheduled_at': scheduled_at,
            'memory_mb': memory_mb,
            'vcpus': vcpus,
            'root_gb': root_gb,
            'ephemeral_gb': ephemeral_gb,
            'display_name': pvc_instance['name'],
            'display_description': pvc_instance['name'],
            'locked': False,
            'instance_type_id': flavor['id'],
            'progress': 0,
            'metadata': metadata,
            'architecture': constants.PPC64,
            'host': utils.normalize_host(pvc_instance['OS-EXT-SRV-ATTR:host']),
            'launched_on': pvc_instance['hostId'],
            'hostname': hostname,
            'node': pvc_instance['OS-EXT-SRV-ATTR:hypervisor_hostname'],
            'access_ip_v4': address4,
            'root_device_name': root_device_name,
            'vm_state': pvc_instance['OS-EXT-STS:vm_state'],
            'task_state': None,
            'power_state': pvc_instance['OS-EXT-STS:power_state']}

        # Get user/tenant from context when importing a new instance not in DB
        if not db_instance:
            # NOTE(boden): can raise if invalid staging user or project
            uid, pid = self._staging_cache.get_staging_user_and_project(True)
            ins['project_id'] = pid
            ins['user_id'] = uid
            # Only update the System_metadata when the new instance is inserted
            ins['system_metadata'] = flavors.save_flavor_info(dict(), flavor)
        else:
            # Get user and project from the DB entry
            ins['user_id'] = db_instance.get('user_id')
            ins['project_id'] = db_instance.get('project_id')
            # Need to update the system metadate when the flavor of
            # the instance changes
            sys_meta = flavors.extract_flavor(db_instance)
            instance_type_id = sys_meta['id']
            if instance_type_id != flavor['id']:
                ins['system_metadata'] = flavors.\
                    save_flavor_info(sys_meta, flavor)

        return (ins, image, flavor)

    def _insert_pvc_instance(self, ctx, pvc_instance):
        """ Translate PowerVC instance into OpenStack instance and insert."""

        if pvc_instance['OS-EXT-STS:vm_state'] == vm_states.ERROR:
            pvc_host = pvc_instance.get(constants.HOST_PROP_NAME)
            pvc_hypervisor = pvc_instance.get(constants.HYPERVISOR_PROP_NAME)
            if pvc_host is None or pvc_hypervisor is None:
                LOG.debug(_("The instance: %s is in the Error State and no "
                            "associated host or hypervisor. Skip to sync" %
                            pvc_instance['id']))
                return

        ins, image, flavor = self._translate_pvc_instance(ctx, pvc_instance)
        security_group_map = self.\
            _get_security_group_for_instance(ctx, pvc_instance)
        new_instance = instance_obj.Instance()
        new_instance.update(ins)
        block_device_map = [block_device.create_image_bdm(image['id'])]
        db_instance = self.compute_api.\
            create_db_entry_for_new_instance(ctx,
                                             flavor,
                                             image,
                                             new_instance,
                                             security_group_map,
                                             block_device_map,
                                             1,
                                             1)
        # The API creates the instance in the BUIDING state, but this
        # instance is actually already built most likely, so we update
        # the state to whatever the state is in PowerVC.
        db_instance = self.compute_api.update(
            ctx, db_instance,
            power_state=pvc_instance['OS-EXT-STS:power_state'],
            vm_state=pvc_instance['OS-EXT-STS:vm_state'],
            task_state=pvc_instance['OS-EXT-STS:task_state'])

        self.sync_volume_attachment(ctx,
                                    ins['metadata'][constants.PVC_ID],
                                    db_instance)

        # Fix the network info.
        local_port_ids = self.driver._service.\
            set_device_id_on_port_by_pvc_instance_uuid(ctx,
                                                       db_instance['uuid'],
                                                       pvc_instance['id'])
        # If neutron agent has synced ports, then go ahead to fix the network,
        # otherwise wait for the next full update.
        if local_port_ids and len(local_port_ids) > 0:
            self._fix_instance_nw_info(ctx, db_instance)

        # Send notification about instance creation due to sync operation
        compute.utils.notify_about_instance_usage(
            self.notifier, ctx, db_instance, 'create.sync', network_info={},
            system_metadata={}, extra_usage_info={})

    # Remove an instance that is not in pvc anymore from local DB.
    # TODO: This is not being used. Do we need to worry about deleting metadata
    # separately in _unregister_instance?
    """
    def _destroy_local_instance(self, ctx, local_instance):
        # Get all metadata
        metadata = self.compute_api.get_instance_metadata(ctx, local_instance)
        # Delete all metadata
        for item in metadata.keys():
            self.compute_api.\
                delete_instance_metadata(ctx, local_instance, item)
        # Delete instance, actually it just marks records deleted
        self.compute_api.delete(ctx, local_instance)
    """

    def sync_volume_attachment(self, ctx, pvc_instance_id, local_instance):
        """Sync volume attachment information in BDM"""
        # Since PowerVC server resp does not contain this info, it is needed
        # now to retrieve it through sending another rest api to list
        # volume attachments.
        attachments = self.driver.list_os_attachments(pvc_instance_id)
        attached_volume_ids = []
        attached_devices = []
        for attachment in attachments:
            # Each instance has a default volume,
            # which is not what we want to show
            if attachment.device != '/dev/sda':
                block_device_map = {}
                vol_id = self.cache_volume.get_by_id(attachment.id)
                if vol_id:
                    block_device_map['volume_id'] = vol_id
                    attached_volume_ids.append(vol_id)
                else:
                    LOG.info(_("No cinder volume for powervc volume: "
                               "%s" % attachment.id))
                    block_device_map['volume_id'] = constants.INVALID_VOLUME_ID
                block_device_map['device_name'] = attachment.device
                attached_devices.append(attachment.device)
                block_device_map['instance_uuid'] = local_instance['uuid']
                block_device_map['connection_info'] = jsonutils.dumps(
                    {"": {},
                     "connection_info": {"driver_volume_type": "",
                                         "data": ""}
                     })
                block_device_map['source_type'] = 'volume'
                block_device_map['destination_type'] = 'volume'
                db_api.block_device_mapping_update_or_create(ctx,
                                                             block_device_map)
        # Removing the BDMs are not in powervc
        leftover_bdms = []
        primitive_instance = obj_base.obj_to_primitive(local_instance)
        local_attachments = self.conductor_api.\
            block_device_mapping_get_all_by_instance(ctx, primitive_instance)
        for local_attachment in local_attachments:
            if not self._is_volume_type(local_attachment):
                continue
            local_volume_id = local_attachment['volume_id']
            if local_volume_id in attached_volume_ids:
                # this volume is still attached
                continue
            if local_volume_id == constants.INVALID_VOLUME_ID:
                # for invalid volume id, just check the device_name
                local_device_name = local_attachment['device_name']
                if local_device_name in attached_devices:
                    # this volume is still attached even it's
                    # volume id is not valid
                    LOG.info(_("retain the volume with device name: %s,  "
                               "although it's volume id is not valid "
                               "yet" % local_device_name))
                    continue
            leftover_bdms.append(local_attachment)

        for deleted_bdm in leftover_bdms:
            LOG.info(_("Removing Block Device Mapping for: "
                       "%s") % deleted_bdm)
            db_api.block_device_mapping_destroy(ctx, deleted_bdm['id'])
            LOG.info(_("Removed Block Device Mapping"))

    def _is_volume_type(self, block_device_mapping):
        """
         Test a block_device_mapping is a volume or not

         :param block_device_mapping: block_device_mapping instance to
                be tested
        """
        if block_device_mapping.get('volume_id') is None:
            return False
        return True

    def _unregister_instance(self, ctx, local_instance, force_delete=False):
        """
        Unregister the instance from the local database. This does not use the
        compute API which would send an RPC to have the instance deleted. The
        instance has already been removed from PowerVC so we just send our
        own notifications locally and remove it from the database.

        :param ctx: The security context
        :param local_instance: The instance dict
        :param force_delete: If True, the instance will be deleted even if the
               task state is set to 'deleting'.
        """
        LOG.debug(_('Enter to unregister instance of %s .') % local_instance)

        # If the instance does not exist then ignore
        if not local_instance:
            LOG.debug(_('Instance does not exist locally'))
            LOG.debug(_('Exit to unregister instance of %s .')
                      % local_instance)
            return

        instance_ref = local_instance

        # If the task state is not set to deleting, set it.
        # If set, then go ahead and delete, which means last time,
        # sth. went wrong when actually delete it.
        if local_instance.get('task_state') != task_states.DELETING:
            # Update the state and send notification for the updated state
            old_ref, instance_ref = db_api.instance_update_and_get_original(
                ctx, local_instance.get('uuid'),
                {'task_state': task_states.DELETING, 'progress': 0})
            notifications.send_update(ctx, old_ref, instance_ref,
                                      service='powervc')
            LOG.debug(_("Sent a notification for the updated state of %s,"
                        "event type is %s")
                      % (instance_ref.get('uuid'), 'powervc'))

        # Delete the instance from the local database
        try:
            db_api.instance_destroy(ctx, local_instance.get('uuid'))
        except Exception:
            LOG.warning(_("Removing PowerVC instance %s in nova failed."),
                        local_instance.get('name'))

        # delete network resource
        # transfer db object to nova instance obj to meet latest community
        # change
        if not isinstance(local_instance, obj_base.NovaObject):
            local_instance = \
                objects.Instance._from_db_object(ctx,
                                                 objects.Instance(),
                                                 local_instance)
        self.network_api.deallocate_for_instance(ctx, local_instance)

        # Send notification about instance deletion due to sync operation
        compute.utils.notify_about_instance_usage(
            self.notifier, ctx, instance_ref, 'delete.sync', network_info={},
            system_metadata={}, extra_usage_info={})
        LOG.debug(_('Send a notification about instance deletion of %s,'
                    'event type is %s')
                  % (instance_ref.get('uuid'), 'delete.sync'))
        LOG.debug(_('Exit to unregister instance of %s .')
                  % local_instance.get('uuid'))

    def _is_pvc_instance(self, ctx, local_instance):
        """
        Check to see if a local instance is synchronized from PowerVC.
        If not, return False
        """

        # Get the uuid of pvc from the local instance.
        metadata = self.compute_api.get_instance_metadata(ctx, local_instance)
        return (constants.PVC_ID in metadata)

    def _is_valid_pvc_instance(self, ctx, local_instance, pvc_instances):
        """
        Check to see if a local instance is in the PowerVC list.
        If not, return False
        """

        # Get the uuid of pvc from the local instance.
        metadata = self.compute_api.get_instance_metadata(ctx, local_instance)
        if constants.PVC_ID not in metadata:
            return False

        local_uuid = metadata[constants.PVC_ID]
        found = False
        for instance in pvc_instances:
            uuid = instance.id
            if local_uuid == uuid:
                found = True
                break
        return found

    def _get_image_from_instance(self, ctx, pvc_instance, db_instance=None):
        """
        Get the corresponding image with a PowerVC instance.
        :param ctx: The security context
        :param pvc_instance: The VM instance from the PowerVC
        :param db_instance: The VM instance in the local database,
                            if it does not exist, set as None.
        :returns: the image of the instance
        """

        rtn = None

        # Try to get the PowerVC image id from the PowerVC instance
        pvc_instance_image_uuid = ''
        pvc_image = pvc_instance.get('image', '')
        if pvc_image != '':
            pvc_instance_image_uuid = pvc_image.get('id', '')

        # Handle with the situation that the instance has already been
        # in the local database
        if db_instance is not None:
            if 'image_ref' in db_instance:
                # If the image is deleted in the Hosting OS,
                # the image will not be deleted physically and just be marked
                # as 'deleted'.
                # So we can get the corresponding image although it is deleted.
                try:
                    local_image = glance.\
                        get_default_image_service().\
                        show(ctx, db_instance.get('image_ref'))
                except Exception as exc:
                    # This exception is used to handle with the situation
                    # that the glance service is crashed.
                    # Return the image as image_reference.
                    LOG.warning("Fail to get the local image: %s"
                                % db_instance.get('image_ref'))
                    LOG.warning("Getting the exception: %s." % str(exc))
                    local_image = {}
                    local_image['id'] = db_instance.get('image_ref')
                    return local_image

                rtn = self._get_image_from_local_db(local_image,
                                                    pvc_instance_image_uuid)
                if rtn is not None:
                    return rtn

        glance_images = self._list_local_images(ctx)

        for image in glance_images:
            rtn = self._get_image_from_local_db(image, pvc_instance_image_uuid)
            if rtn is not None:
                break

        if rtn is None:
            rtn = self.get_default_image(ctx)

        return rtn

    def _get_image_from_local_db(self, image, pvc_instance_image_uuid):
        """
        This method is used to get the local image with the specified
        PowerVC image UUID
        :param image: the image from the local database
        :pvc_instance_image_uuid: the UUID of the PowerVC image
        :returns: if there is a proper image in the local database,
                  return this image, else return None
        """
        rtn = None
        local_image_pvc_uuid = None
        if 'properties' in image and 'powervc_uuid' in image['properties']:
                local_image_pvc_uuid = image['properties']['powervc_uuid']
                if pvc_instance_image_uuid != '' and \
                        pvc_instance_image_uuid == local_image_pvc_uuid:
                    LOG.info("Get the image %s from the local database."
                             % image['id'])
                    rtn = image
        return rtn

    def _list_local_images(self, ctx):
        """
        This method is used to list all the local images.
        :param ctx: The security context
        :returns : if the local glance service is active,
                    return the image list, else return {}
        """
        params = {}
        filters = {}
        filters['limit'] = CONF.powervc.image_limit
        params['filters'] = filters

        try:
            glance_images = glance.\
                get_default_image_service().detail(ctx, **params)
        except Exception as exc:
            LOG.warning("Get the exception %s during listing the images"
                        % str(exc))
            return {}
        return glance_images

    def _get_flavor_from_instance(self, ctx, pvc_instance, db_instance=None):
        """
        Get the local flavor through the PowerVC instance
        """
        rtn = None

        # Get the flavorid from the PowerVC instance
        pvc_flavor = pvc_instance['flavor']
        pvc_flavor_id = pvc_flavor['id']

        if db_instance is not None:
            # Handle the stituation that the instance is deployed
            # through the hosting OS

            # Get the flavor id of the db instance
            instance_type_id = db_instance['instance_type_id']
            # Get the db instance flavor
            db_instance_flavor = self._get_local_flavor(ctx, instance_type_id)
            # Get the PowerVC VM instance flavor
            pvc_flavor = self.driver.get_pvc_flavor_by_flavor_id(pvc_flavor_id)

            # Check whether the instance has been resized
            pvc_flavor_dict = pvc_flavor.__dict__

            if (db_instance_flavor['memory_mb'] ==
                pvc_flavor_dict['ram'] and
                db_instance_flavor['vcpus'] ==
                pvc_flavor_dict['vcpus'] and
                db_instance_flavor['root_gb'] ==
                pvc_flavor_dict['disk'] and
                db_instance_flavor['ephemeral_gb'] ==
                    pvc_flavor_dict.get('OS-FLV-EXT-DATA:ephemeral', 0)):
                return db_instance_flavor

        if rtn is None:
            LOG.debug(_("Get flavor from pvc"))
            local_flavorid = CONF.powervc.flavor_prefix + pvc_flavor_id
            rtn = self._get_pvc_flavor(ctx, pvc_flavor_id, local_flavorid)

        if rtn is None:
            # Get the default flavor
            rtn = flavors.get_default_flavor()
        return rtn

    def _get_local_flavor(self, ctx, flavor_id):

        """
        Try to get the local flavor.

        This method is used to handle with the situation that
        the VM instance is deployed with the local flavor
        through the hosting machine
        """
        rtn = None
        try:
            flv = flavors.get_flavor(flavor_id, ctx)
            rtn = flv
        except Exception:
            LOG.info(_("Return None from _get_local_flavor and "
                       "exception caught"))

        return rtn

    def _get_pvc_flavor(self, ctx, pvc_flavor_id, local_flavorid):

        """
        Try to get the sync PowerVC flavor.
        This method is used to handle with the situation that
        the VM instance is deployed with the PowerVC flavor
        through the hosting machine or the VM instance is synced
        from the PowerVC.
        """
        rtn = None

        try:
            rtn = flavors.get_flavor_by_flavor_id(local_flavorid, ctx)
        except Exception:
                # PowerVC instance is created with private flavor which is not
                # synced
                LOG.info(_("PowerVC instance is created with private flavor "
                           "which is not synced"))
                if rtn is None:
                    try:
                        pvc_flavor = self.driver.\
                            get_pvc_flavor_by_flavor_id(pvc_flavor_id)

                        if pvc_flavor is not None:
                            pvc_flavor_dict = pvc_flavor.__dict__
                            memory = pvc_flavor_dict['ram']
                            vcpus = pvc_flavor_dict['vcpus']
                            root_gb = pvc_flavor_dict['disk']
                            ephemeral_gb = pvc_flavor_dict.get(
                                'OS-FLV-EXT-DATA:ephemeral', 0)

                            p_filter = {'min_memory_mb': memory,
                                        'min_root_gb': root_gb,
                                        'is_public': True,
                                        'disabled': False}
                            rtns = flavors.get_all_flavors(ctx,
                                                           filters=p_filter)

                            # The PowerVC driver will not sync the dynamic
                            # flavor. When the PowerVC instance is created by
                            # the dynamic flavor and we can not get the similar
                            # flavor, we will return the first flavor which the
                            # memory, cpu and disk of is bigger than the
                            # dynamic flavor

                            for key in rtns.keys():
                                if memory <= rtns[key].get('memory_mb')\
                                    and vcpus <= rtns[key].get('vcpus')\
                                    and root_gb <= rtns[key].get('root_gb')\
                                    and ephemeral_gb <= rtns[key].\
                                        get('ephemeral_gb'):
                                    if rtns[key]['name'].find('PVC') != -1:
                                        rtn = rtns[key]
                                        LOG.info(_("Return the first public "
                                                   "PowerVC flavor that fits "
                                                   "into the resource "
                                                   "instance instead"), rtn)
                                        break
                            if rtn is None:
                                for key in rtns.keys():
                                    if memory <= rtns[key].get('memory_mb')\
                                            and vcpus <= rtns[key].get('vcpus')\
                                            and root_gb <= rtns[key].\
                                            get('root_gb')\
                                            and ephemeral_gb <= rtns[key].\
                                            get('ephemeral_gb'):
                                        rtn = rtns[key]
                                        LOG.info(_("Return the"
                                                   "first public "
                                                   "PowerVC flavor"
                                                   " that fits "
                                                   "into the resource "
                                                   "instance instead"), rtn)
                                        break
                    except Exception:
                        if rtn is None:
                            # Get the default flavor when can not get the
                            # corresponding flavor with the specified
                            # PowerVC instance
                            LOG.info("Get the default flavor")
                            rtn = flavors.get_default_flavor()

        return rtn

    # FIXME: get a security group, shall we map the security group?
    def _get_security_group_for_instance(self, ctx, pvc_instance):
        return ['default']

    def _create_local_listeners(self, ctx):
        """Listen for local(OpenStack) compute node notifications."""

        LOG.debug("Enter _create_local_listeners method")

        trans = transport.get_transport(cfg.AMQP_OPENSTACK_CONF)
        targets = [
            target.Target(exchange='nova', topic='notifications')
        ]
        endpoint = messaging.NotificationEndpoint(log=LOG, sec_context=ctx)

        # Instance state changes
        endpoint.register_handler([
            constants.EVENT_INSTANCE_RESIZE,
            constants.EVENT_INSTANCE_RESIZE_CONFIRM,
            constants.EVENT_INSTANCE_LIVE_MIGRATE],
            self._handle_local_deferred_host_updates)

        # Instance creation
        endpoint.register_handler(constants.EVENT_INSTANCE_CREATE,
                                  self._handle_local_instance_create)
        endpoints = [
            endpoint,
        ]

        LOG.debug("Starting to listen...... ")

        local_nova_listener = listener.\
            get_notification_listener(trans, targets, endpoints,
                                      allow_requeue=False)
        messaging.start_notification_listener(local_nova_listener)

        LOG.debug("Exit _create_local_listeners method")

    def _create_powervc_listeners(self, ctx):
        """Listen for out-of-band changes made in PowerVC.

        Any changes made directly in PowerVC will be reflected in the local OS.

        :param: ctx The security context
        """

        LOG.debug("Enter _create_powervc_listeners method")

        trans = transport.get_transport(cfg.AMQP_POWERVC_CONF)
        targets = [
            target.Target(exchange='nova', topic='notifications')
        ]
        endpoint = messaging.NotificationEndpoint(log=LOG, sec_context=ctx)

        # Instance creation
        endpoint.register_handler(constants.EVENT_INSTANCE_CREATE,
                                  self._handle_powervc_instance_create)

        # onboarding end
        endpoint.register_handler(constants.EVENT_INSTANCE_IMPORT,
                                  self._handle_powervc_instance_create)

        # Instance deletion
        endpoint.register_handler(constants.EVENT_INSTANCE_DELETE,
                                  self._handle_powervc_instance_delete)

        # Instance state changes
        endpoint.register_handler([
            constants.EVENT_INSTANCE_UPDATE,
            constants.EVENT_INSTANCE_POWER_ON,
            constants.EVENT_INSTANCE_POWER_OFF,
            constants.EVENT_INSTANCE_RESIZE,
            constants.EVENT_INSTANCE_RESIZE_CONFIRM,
            constants.EVENT_INSTANCE_LIVE_MIGRATE,
            constants.EVENT_INSTANCE_LIVE_MIGRATE_ROLLBACK,
            constants.EVENT_INSTANCE_SNAPSHOT],
            self._handle_powervc_instance_state)

        # Instance volume attach/detach event handling
        endpoint.register_handler([
            constants.EVENT_INSTANCE_VOLUME_ATTACH,
            constants.EVENT_INSTANCE_VOLUME_DETACH],
            self._handle_volume_attach_or_detach)

        endpoints = [
            endpoint,
        ]

        LOG.debug("Starting to listen...... ")

        pvc_nova_listener = listener.\
            get_notification_listener(trans, targets, endpoints,
                                      allow_requeue=False)
        messaging.start_notification_listener(pvc_nova_listener)

        LOG.debug("Exit _create_powervc_listeners method")

    def _handle_local_instance_create(self,
                                      context=None,
                                      ctxt=None,
                                      event_type=None,
                                      payload=None):
        """Handle local deployment completed messages sent from the
        hosting OS. This is need so we can tell the hosting OS
        to sync the latest state from PowerVC. Once a deployment
        completes in PowerVC the instances go into activating task
        state.  We want to make sure we reflect this as soon as it
        happens and based on timing its best to check when we report
        back from spawn thus sending the completed event.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        hosting_id = payload.get('instance_id')

        # Attempt to get the local instance.
        instance = None
        try:
            instance = db.instance_get_by_uuid(context, hosting_id)
        except exception.InstanceNotFound:
            LOG.debug(_("Local Instance %s Not Found") % hosting_id)
            return

        # Get the PVC instance
        pvcid = self.driver._get_pvcid_from_metadata(instance)
        powervc_instance = self.driver.get_instance(pvcid)

        if powervc_instance:
            self._update_state(context, instance, powervc_instance, pvcid,
                               constants.EVENT_INSTANCE_UPDATE)
        else:
            LOG.debug(_('PowerVC instance could not be found'))

    def _handle_local_deferred_host_updates(self,
                                            context=None,
                                            ctxt=None,
                                            event_type=None,
                                            payload=None):
        """Handle live migration completed messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        hosting_id = self._pre_process_message(payload)

        # Attempt to get the local instance.
        instance = None
        try:
            instance = db.instance_get_by_uuid(context, hosting_id)
        except exception.InstanceNotFound:
            LOG.debug(_("Local Instance %s Not Found") % hosting_id)
            return

        # See if the instance is deferring host scheduling.
        # If it is exit immediately.
        if not self.driver._check_defer_placement(instance):
            LOG.debug(_("Local Instance %s did not defer scheduling")
                      % hosting_id)
            return

        # Get the PVC instance
        pvcid = self.driver._get_pvcid_from_metadata(instance)

        if pvcid is not None:
            if instance:
                # Convert to primative format from db object
                instance = jsonutils.to_primitive(instance)
                try:
                    self.driver.update_instance_host(context, instance)
                except Exception:
                    LOG.debug(_('Problem updating local instance host '
                                'information, instance: %s') % instance['id'])
            else:
                LOG.debug(_('Tried to update instance host value but the'
                            ' instance could not be found in PowerVC'))

    def _handle_powervc_instance_create(self,
                                        context=None,
                                        ctxt=None,
                                        event_type=None,
                                        payload=None):
        """Handle instance create messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        powervc_instance_id = self._pre_process_message(payload)

        # Check for matching local instance
        matched_instances = self._get_local_instance_by_pvc_id(
            context, powervc_instance_id)

        # If the instance already exists locally then ignore
        if len(matched_instances) > 0:
            LOG.debug(_('Instance already exists locally'))
            return

        # Get the newly added PowerVC instance and add it to the local OS
        instance = self.driver.get_instance(powervc_instance_id)
        # Filter out the instance in scg that is not specified in conf
        instance_scg_id = instance.storage_connectivity_group_id
        our_scg_id_list = [scg.id for scg
                           in utills.get_utils().get_our_scg_list()]
        if instance_scg_id and instance_scg_id not in our_scg_id_list:
            instance = None

        if instance:
            instance = instance.__dict__
            try:
                self._add_local_instance(context, instance)
            except Exception as e:
                LOG.warning(_("Failed to insert instance due to: %s ")
                            % str(e))
        else:
            LOG.debug(_('Tried to add newly created instance but it could not '
                      'be found in PowerVC'))

    def _handle_powervc_instance_delete(self,
                                        context=None,
                                        ctxt=None,
                                        event_type=None,
                                        payload=None):
        """Handle instance delete messages sent from PowerVC.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        powervc_instance_id = self._pre_process_message(payload)

        # Check for matching local instance
        matched_instances = self._get_local_instance_by_pvc_id(
            context, powervc_instance_id)

        # If the instance does not exist then ignore
        if len(matched_instances) == 0:
            LOG.debug(_('Instance does not exist locally'))
            return

        # Remove the instance from the local OS
        self._remove_local_instance(context, matched_instances[0])

    def _handle_powervc_instance_state(self,
                                       context=None,
                                       ctxt=None,
                                       event_type=None,
                                       payload=None):
        """Handle instance state changes sent from PowerVC. This includes
        instance update and all other state changes caused by events like
        power on, power off, resize, live migration, and snapshot.

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        powervc_instance_id = self._pre_process_message(payload)

        local_instance = self.\
            _get_matched_instance_by_pvc_id(context, powervc_instance_id)

        if not local_instance:
            return

        powervc_instance = self.driver.get_instance(powervc_instance_id)

        self._update_state(context, local_instance, powervc_instance,
                           powervc_instance_id, event_type)

    def _handle_volume_attach_or_detach(self,
                                        context=None,
                                        ctxt=None,
                                        event_type=None,
                                        payload=None):
        """Handle out of band volume attach or detach event

        :param: context The security context
        :param: ctxt message context
        :param: event_type message event type
        :param: payload The AMQP message sent from OpenStack (dictionary)
        """
        powervc_instance_id = self._pre_process_message(payload)

        local_instance = self.\
            _get_matched_instance_by_pvc_id(context, powervc_instance_id)
        if not local_instance:
            return

        powervc_volume_id = payload.get('volume_id')
        if powervc_volume_id is None:
            LOG.warning(_('no valid volume for powervc instance %s') %
                        powervc_instance_id)
            return
        vol_id = self.cache_volume.get_by_id(powervc_volume_id)
        if vol_id is None:
            # get the local volume info and cache it
            LOG.debug(_("Get the local volume info for powervc volume with id:"
                        " %s") % powervc_volume_id)
            local_volume_id = self.driver.\
                get_local_volume_id_from_pvc_id(powervc_volume_id)
            LOG.debug(_("Finished to get the local volume info for powervc "
                        "volume with id: %s") % powervc_volume_id)
            if local_volume_id is None:
                # continue to process, just log warning
                LOG.warning(_('volume does not exist locally for remote '
                            'volume: %s') % powervc_volume_id)
            else:
                self.cache_volume.set_by_id(powervc_volume_id, local_volume_id)

        self.sync_volume_attachment(context, powervc_instance_id,
                                    local_instance)

    def _pre_process_message(self, payload):
        """Logging the event type and return the instance id of the nova server
        instance in the event

        :param: payload The AMQP message sent from OpenStack (dictionary)
        :returns instance id triggering the event
        """
        instance_id = payload.get('instance_id')
        return instance_id

    def _get_matched_instance_by_pvc_id(self, context, pvc_id):
        """
        Get the desired local instance from the powervc instance id, if no
        matched local instance, then return None, if more than one matched
        local instances, then log a warning message, only return the first one

        :param: message The AMQP message sent from OpenStack (dictionary)
        :returns the matched local instance for remote instance in powervc
        """
        # Get the matching local instance
        matched_instances = self._get_local_instance_by_pvc_id(
            context, pvc_id)

        # If the instance does not exist locally then ignore
        if len(matched_instances) == 0:
            LOG.info(_("Instance with powervc id %s does not exist "
                       "locally") % pvc_id)
            return None

        # Warn if more than one local instance matches the PowerVC instance
        if len(matched_instances) > 1:
            LOG.warning(_('More than one instance in DB '
                          'match one PowerVC instance: %s' %
                          (pvc_id)))
            # TODO: We should do something about this but scheduling a sync
            # won't help since that does nothing to remove duplicate local
            # instances.

        # Get the PowerVC instance so we can compare it to the local instance
        return matched_instances[0]

    def _update_state(self, context, local_instance, powervc_instance,
                      powervc_instance_id, event_type):
        '''
        Utility method for updatng an instance for local and
        powervc based messages.

        :param: context The security context
        :param: local_instance The database local instance
        :param: powervc_instance The powerVC instance
        :param: powervc_instance_id The powerVC instance id
        :param: event_type The original notification event type
        '''
        # Warn if PowerVC instance is not found
        if powervc_instance is None:
            LOG.warning(_('PowerVC instance could not be found: %s' %
                        (powervc_instance_id)))
            self._schedule_instance_sync(powervc_instance_id)
            return

        powervc_instance = powervc_instance.__dict__

        # Get the local and PowerVC VM and task states so that we can compare
        # them.
        states = {
            'vm_local': local_instance.get('vm_state'),
            'vm_powervc': powervc_instance.get('OS-EXT-STS:vm_state'),
            'task_local': local_instance.get('task_state'),
            'task_powervc': powervc_instance.get('OS-EXT-STS:task_state')
        }

        # Check if the current VM and task states permit a state change
        # for the given event type. If not then we stop here.
        if not self._can_apply_state_update(event_type, **states):

            # We can't apply the state update because the current states do not
            # allow it. If the local instance is not performing a task and the
            # states are not the same then we need to sync.
            if states['task_local'] is None and not (
                    self._instance_states_equal(**states)):
                LOG.warning(_("No local task but the states don't match. "
                            "Scheduling a sync."))
                self._schedule_instance_sync(powervc_instance_id)
            return

        # Get updated instance attributes
        updated_instance, unused_image, unused_flavor = \
            self._translate_pvc_instance(context, powervc_instance,
                                         local_instance)

        # In order to support the rename function in the Hosting OS, we will
        # avoid the name of the instance is updated.
        # In this situation, the name of the same instance will be different in
        # the hosting OS and PowerVC.
        updated_instance['display_name'] = local_instance.get('display_name')

        # Apply the VM and task state to the updated instance properties based
        # on the event type.
        updated_instance = self._apply_state_to_instance_update(
            event_type, updated_instance, **states)

        # Call the compute API to update the local instance
        instance_ref = self.compute_api.update(context, local_instance,
                                               **updated_instance)

        # Send sync notification
        self._send_instance_sync_notification(context, event_type,
                                              instance_ref)

    def _send_instance_sync_notification(self, context, event_type, instance):
        """
        Send a sync notification message based on the given event type.

        :param: context The security context
        :param: event_type The original notification event type
        :param: instance The updated local instance
        """
        # Instance update events do not result in a sync notification
        if event_type == constants.EVENT_INSTANCE_UPDATE:
            return

        tokens = event_type.split('.')[2:]
        tokens[-1] = constants.SYNC_EVENT_SUFFIX
        event = '.'.join(tokens)
        LOG.debug(_('Sending instance sync notification: %s' % (event)))
        compute.utils.notify_about_instance_usage(self.notifier, context,
                                                  instance, event,
                                                  network_info={},
                                                  system_metadata={},
                                                  extra_usage_info={})

    def _can_apply_state_update(self, event_type, **states):
        """
        Determine if the instance state update can be applied based on the
        given local and PowerVC VM and task states.

        For instance update events, the instance should always be updated even
        if the states haven't changed. For other events it will depend on the
        current VM and task state.

        :param: event_type The notification event type
        :param: states VM and task states for the local and PowerVC instance
        """
        # If the local instance task state is anything other than None then
        # we shouldn't interrupt, besides activating.  When a deployment
        # happens on PowerVC, the status is active but the task state is
        # activating. We need to sync the activating task state so that
        # is why its special cased.
        if (states['task_local'] is not None and
                states['task_local'] != 'activating'):
                return False

        # For instance update events the instance properties should always
        # be updated.
        if event_type == constants.EVENT_INSTANCE_UPDATE:
            return True

        # For power_on event the local instance must be STOPPED and the
        # PowerVC instance must be ACTIVE.
        if event_type == constants.EVENT_INSTANCE_POWER_ON:
            return states['vm_local'] == vm_states.STOPPED and \
                states['vm_powervc'] == vm_states.ACTIVE

        # For power_off event the local instance must be ACTIVE and the
        # PowerVC instance must be STOPPED.
        if event_type == constants.EVENT_INSTANCE_POWER_OFF:
            return states['vm_local'] == vm_states.ACTIVE and \
                states['vm_powervc'] == vm_states.STOPPED

        # For finish_resize event the local instance must be ACTIVE or STOPPED
        # and the PowerVC instance must be RESIZED.
        if event_type == constants.EVENT_INSTANCE_RESIZE:
            return ((states['vm_local'] == vm_states.ACTIVE or
                    states['vm_local'] == vm_states.STOPPED) and
                    states['vm_powervc'] == vm_states.RESIZED)

        # For resize confirm event the local instance must be RESIZED and the
        # PowerVC instance must be ACTIVE or STOPPED.
        if event_type == constants.EVENT_INSTANCE_RESIZE_CONFIRM:
            return (states['vm_local'] == vm_states.RESIZED and
                    (states['vm_powervc'] == vm_states.ACTIVE or
                     states['vm_powervc'] == vm_states.STOPPED))

        # For snapshot event the local instance must be ACTIVE or STOPPED and
        # the PowerVC instance must be the same.
        if event_type == constants.EVENT_INSTANCE_SNAPSHOT:
            return ((states['vm_local'] == vm_states.ACTIVE and
                    states['vm_powervc'] == vm_states.ACTIVE) or
                    (states['vm_local'] == vm_states.STOPPED and
                     states['vm_powervc'] == vm_states.STOPPED))

        # For the other instance events the local instance VM state and the
        # PowerVC VM state must both be ACTIVE.
        return states['vm_local'] == vm_states.ACTIVE and (
            states['vm_powervc'] == vm_states.ACTIVE)

    def _instance_states_equal(self, **states):
        """
        Determine if the local and PowerVC instance states are the same.

        :param: states VM and task states for the local and PowerVC instance
        """
        return states['vm_local'] == states['vm_powervc'] and (
            states['task_local'] == states['task_powervc'])

    def _apply_state_to_instance_update(self, event_type, updated_instance,
                                        **states):
        """
        Apply the vm_state and task_state properties to the updated instance
        properties. The new vm_state and task_state will depend on the type
        of event that triggered the state change. The initial updated instance
        properties include the VM state already updated to match the PowerVC
        VM state and the task state set to None.

        :param: event_type The notification event type
        :param: updated_instance The updated instance properties from PowerVC
        :param: states VM and task states for the local and PowerVC instance
        """
        # For instance updates we have to do some checks to determine if we
        # should update the VM and task states.
        if event_type == constants.EVENT_INSTANCE_UPDATE:
            return self._apply_state_update(updated_instance, **states)

        # For other event types we don't update the task state
        del updated_instance['task_state']

        # We only update the VM state for the following event types
        vm_state_events = [constants.EVENT_INSTANCE_POWER_ON,
                           constants.EVENT_INSTANCE_POWER_OFF]
        if event_type not in vm_state_events:
            del updated_instance['vm_state']

        return updated_instance

    def _apply_state_update(self, updated_instance, **states):
        """
        Apply the new vm_state and task_state properties for the instance
        update event.

        :param: updated_instance The updated instance properties from PowerVC
        :param: states VM and task states for the local and PowerVC instance
        """
        # If the PowerVC VM state moves into or out of ERROR state then the
        # local instance VM state must be updated to match.
        if (states['vm_local'] == vm_states.ERROR and (
                states['vm_powervc'] != vm_states.ERROR) or
                (states['vm_local'] != vm_states.ERROR and
                 states['vm_powervc'] == vm_states.ERROR)):
            # The updated instance attributes already has the VM state set to
            # match the PowerVC VM state.
            LOG.debug(_('VM state change: %s --> %s' %
                      (str(states['vm_local']), str(states['vm_powervc']))))
        else:
            # Otherwise remove the VM state from the update
            del updated_instance['vm_state']

        # If the PowerVC VM state is ACTIVE and the task state moves into or
        # out of ACTIVATING then the local task state must be updated to
        # match. Enforce strict control of the expected task states.
        if states['vm_powervc'] == vm_states.ACTIVE and (
            # Sync task state to activating.
            (states['task_local'] is None and
             states['task_powervc'] == pvc_task_states.ACTIVATING) or
            # Sync task state from activating to None
            (states['task_local'] == pvc_task_states.ACTIVATING and
             states['task_powervc'] is None)):
                updated_instance.update({'task_state': states['task_powervc']})
                LOG.debug(_('Task state change: %s --> %s' %
                            (str(states['task_local']),
                             str(states['task_powervc']))))
        else:
            # Otherwise remove the task state from the update
            del updated_instance['task_state']

        return updated_instance

    def _schedule_instance_sync(self, powervc_instance_id):
        """
        Schedule a sync for the given PowerVC instance ID. A sync will occur
        at the next instance sync interval for marked instances.

        :param: powervc_instance_id The ID of the PowerVC instance that needs
                                    to be synced.
        """
        self.sync_instances[powervc_instance_id] = True

    def _remove_local_instance(self, context, local_instance,
                               force_delete=False):
        """Remove the local instance if it's not performing a task and
        its vm_state is not BUILDING|DELETED|SOFT_DELETED|DELETING(force).
        """
        LOG.debug(_('Enter to remove local instance of %s')
                  % local_instance.get('uuid'))

        local_task_state = local_instance.get('task_state')
        local_vm_state = local_instance.get('vm_state')
        LOG.debug(_('Remove local instance %(ins)s, vm_state: %(vm)s, '
                    'task_state: %(task)s'
                    % {'ins': local_instance.get('uuid'),
                       'vm': str(local_vm_state),
                       'task': str(local_task_state)}))

        if (
            local_vm_state == vm_states.DELETED or
            local_vm_state == vm_states.SOFT_DELETED or
            (local_task_state == task_states.DELETING and not force_delete)
        ):
            LOG.debug(_('Skip remove local_instance,'
                        'Because the VM already deleted or being deleted'))
            return False

        if (
            (local_task_state is None or
             local_task_state == pvc_task_states.ACTIVATING or
             (local_task_state == task_states.DELETING and
              force_delete)) and
            local_vm_state != vm_states.BUILDING
        ):
            self._unregister_instance(context, local_instance)
            LOG.debug(_('Exit to remove local instance of %s')
                      % local_instance.get('uuid'))
            return True

        LOG.debug(_('Skip remove local_instance %(ins)s from local DB, because'
                    'task_state is %(task_state)s, vm_state is %(vm_state)s'
                    % {'ins': local_instance,
                       'task_state': local_task_state,
                       'vm_state': local_vm_state}))
        return False

    def _add_local_instance(self, context, pvc_instance):
        """Add a new local instance if the PowerVC instance is not
        performing a task or performing a 'ACTIVATING' task,
        and its vm_state is not BUILDING, RESIZED,
        DELETED, SOFT_DELETED.
        """
        pvc_task_state = pvc_instance['OS-EXT-STS:task_state']
        pvc_vm_state = pvc_instance['OS-EXT-STS:vm_state']
        if (
            (pvc_task_state is None or
             pvc_task_state == pvc_task_states.ACTIVATING) and
            pvc_vm_state != vm_states.BUILDING and
            pvc_vm_state != vm_states.RESIZED and
            pvc_vm_state != vm_states.DELETED and
            pvc_vm_state != vm_states.SOFT_DELETED
        ):
            self._insert_pvc_instance(context, pvc_instance)
            return True

        LOG.debug(_('Skip add pvc_instance %(ins)s to local DB, because'
                    'task_state is %(task_state)s, vm_state is %(vm_state)s'
                    % {'ins': pvc_instance,
                       'task_state': pvc_task_state,
                       'vm_state': pvc_vm_state}))
        return False

    def _update_local_instance(self, context, local_instance, pvc_instance):
        """Update the local instance if both the local instance and the
        PowerVC instance are not performing a task.
        """
        # Syncing RESIZED state can create problems for the local instance.
        # The hosting OpenStack maintains a list of resizes initiated from
        # it so users can confirm them later. Overwriting the local RESIZED
        # state will cause resizes to be left in the list and never confirmed.
        # Syncing the PowerVC RESIZED state will not work either.  The local
        # instance does not have the correct internal state to allow resize
        # confirmation.
        local_task_state = local_instance.get('task_state')
        pvc_task_state = pvc_instance['OS-EXT-STS:task_state']
        local_vm_state = local_instance.get('vm_state')
        pvc_vm_state = pvc_instance['OS-EXT-STS:vm_state']
        if (
            (local_task_state is None or
             local_task_state == pvc_task_states.ACTIVATING) and
            pvc_task_state is None and
            pvc_vm_state != vm_states.RESIZED and
            local_vm_state != vm_states.RESIZED
        ):
            self._sync_existing_instance(context,
                                         local_instance,
                                         pvc_instance)
            return True

        local_id = local_instance.get('uuid')
        if (pvc_task_state is None and
           (pvc_vm_state == vm_states.ACTIVE or
            pvc_vm_state == vm_states.ERROR) and
                local_task_state == task_states.SPAWNING):

            # Defer update local vm when powervc vm ids in spawning status
            if local_id in self.defer_update_local_vm_in_spawning_ids:
                LOG.info(_('Update %(pvc_ins)s to %(local_ins)s, when'
                           'pvc_task_state is %(pvc_task_state)s,'
                           'pvc_vm_state is %(pvc_vm_state)s,'
                           'local_task_state is %(local_task_state)s,'
                           'local_vm_state is %(local_vm_state)s'
                           % {'pvc_ins': pvc_instance,
                              'local_ins': local_instance,
                              'pvc_task_state': pvc_task_state,
                              'pvc_vm_state': pvc_vm_state,
                              'local_task_state': local_task_state,
                              'local_vm_state': local_vm_state}))

                self._sync_existing_instance(context,
                                             local_instance,
                                             pvc_instance)

                # send out event for instance create finished
                compute.utils.notify_about_instance_usage(self.notifier,
                                                          context,
                                                          local_instance,
                                                          "create.sync",
                                                          network_info={},
                                                          system_metadata={},
                                                          extra_usage_info={})
                self.defer_update_local_vm_in_spawning_ids.remove(local_id)
            else:
                self.defer_update_local_vm_in_spawning_ids.append(local_id)
                LOG.info(_('VM: %(uuid)s is in spawning status, defer update.'
                           ' Just add uuid to list and will update next time.'
                           % {'uuid': local_id}))

            return True

        LOG.debug(_('Skip update %(pvc_ins)s to %(local_ins)s, because'
                    'pvc_task_state is %(pvc_task_state)s,'
                    'pvc_vm_state is %(pvc_vm_state)s,'
                    'local_task_state is %(local_task_state)s,'
                    'local_vm_state is %(local_vm_state)s'
                    % {'pvc_ins': pvc_instance,
                       'local_ins': local_instance,
                       'pvc_task_state': pvc_task_state,
                       'pvc_vm_state': pvc_vm_state,
                       'local_task_state': local_task_state,
                       'local_vm_state': local_vm_state}))
        return False

    def _periodic_instance_sync(self, context, instance_ids=None):
        """
        Called to synchronize instances after initial boot. This does almost
        the same thing as the synchronize that happens on boot except this
        function will check that the instance states meet certain requirements
        before adding, removing, or updating them locally.

        :param: context The security context
        :param: instance_ids List of PowerVC instance IDs to sync
        """
        # Some counters to record instances modified
        count_new_instances = 0
        count_updated_instances = 0
        count_deleted_instances = 0
        count_errors = 0

        # If a list of instance IDs is passed in then this is a targeted sync
        # operation and not a full sync.
        is_full_sync = not instance_ids

        # If this is a full sync then reset the marked instances map, otherwise
        # just remove instances we are about to update. Do this up front so
        # that we minimize the likelihood of losing any instances that might
        # get marked during the sync operation.
        if is_full_sync:
            self.sync_instances = {}
        else:
            for instance_id in instance_ids:
                del self.sync_instances[instance_id]

        # Get both lists from local DB and PowerVC
        pvc_instances = []
        local_instances = []
        if is_full_sync:
            pvc_instances = self.driver.list_instances()
            local_instances = self._get_all_local_instances(context)
        else:
            for idx in instance_ids:
                try:
                    instance = self.driver.get_instance(idx)
                    pvc_instances.append(instance)
                except Exception, e:
                    LOG.warning(_('Error occured during get pvc instance \
                    [id:%s], %s' % (idx, e)))

        # Sync. from PowerVC to local nova DB, to insert new instances and
        # update existing instances.
        for index, instance in enumerate(pvc_instances):
            try:

                greenthread.sleep(0)

                """
                 A sample of returned instance from PowerVC:
                 https://w3-connections.ibm.com/wikis/home?lang=en-us#!/wiki/
                 We32ccda54f51_4ede_bfd6_8f9cc4b70d23/page/REST%20Responses
                """
                # If we are syncing a set of given PowerVC instance IDs then we
                # first check if the PowerVC instance exists.If it doesn't then
                # we attempt to delete the local corresponding
                # instance and move on.
                if not is_full_sync and instance is None:
                    matched_instances = self.\
                        _get_local_instance_by_pvc_id(context,
                                                      instance_ids[index])
                    for local_instance in matched_instances:
                        if self._remove_local_instance(context,
                                                       local_instance):
                            count_deleted_instances += 1
                    continue

                # Convert PowerVC instance object to dictionary
                pvc_instance = instance.__dict__
                matched_instances = self.\
                    _get_local_instance_by_pvc_id(context, pvc_instance['id'])

                # If not found locally then try to add the new instance
                if len(matched_instances) == 0:
                    if self._add_local_instance(context,
                                                pvc_instance):
                        count_new_instances += 1
                    continue

                if len(matched_instances) > 1:
                    LOG.warning(_('More than one local instance matches one '
                                'PowerVC instance: %s' % (pvc_instance['id'])))
                local_instance = matched_instances[0]

                # Local instance exists so try to update it
                if self._update_local_instance(context,
                                               local_instance,
                                               pvc_instance):
                    count_updated_instances += 1
            except Exception, e:
                count_errors += 1
                LOG.exception(_("_periodic_instance_sync pvc to local: %s")
                              % e)
        # Sync. from local nova DB to PowerVC, to remove invalid instances
        # that are not in PowerVC anymore. This only happens during a full
        # sync of all instances.
        for local_instance in local_instances:
            try:

                greenthread.sleep(0)

                if not self._is_valid_pvc_instance(context, local_instance,
                                                   pvc_instances):
                    if self._remove_local_instance(context,
                                                   local_instance,
                                                   True):
                        count_deleted_instances += 1
            except Exception, e:
                count_errors += 1
                LOG.exception(_("_periodic_instance_sync local to pvc: %s")
                              % e)
        LOG.info(_("""
                    *******************************
                    Instance sync. is complete.
                    Full sync: %(full_sync)s
                    [ %(insert)s inserted,
                      %(update)s updated,
                      %(delete)s deleted]
                    Error: %(error)s
                    *******************************
                 """ %
                 {'full_sync': is_full_sync,
                  'insert': count_new_instances,
                  'update': count_updated_instances,
                  'delete': count_deleted_instances,
                  'error': count_errors}))

    def _start_periodic_instance_flavor_sync(self, context):
        """
        Initialize the periodic syncing of instances from PowerVC into the
        local OS. The powervc_instance_sync_interval config property determines
        how often the sync will occur, and the
        powervc_full_instance_sync_frequency config property determines the
        number of marked instance sync operations between full instance syncs.
        Now this also launches flavor periodic sync.

        :param: context The security context
        """
        # Enforce some minimum values for the sync interval properties
        # TODO: Minimum values should at least be documented
        conf_sync = CONF.powervc.instance_sync_interval
        conf_full_sync = CONF.powervc.full_instance_sync_frequency
        sync_interval = conf_sync if conf_sync > 10 else 10
        full_sync_frequency = conf_full_sync if conf_full_sync > 2 else 2
        self._instance_sync_counter = 0

        # Decorator of ignoring most of exceptions except some specified
        def exception_swallowed(func):
            def __swallowed():
                LOG.debug(_('Begin: decorator of exception_swallowed for %s' %
                            str(func)))
                try:
                    func()
                except LoopingCallDone, lcd:
                    LOG.error(_('Exception: LoopingCallDone: ' + str(lcd)))
                    raise lcd
                except Exception, e:
                    LOG.error(_('Exception: Exception: ' + str(e)))
                LOG.debug(_('End: decorator of exception_swallowed for %s' %
                            str(func)))
            return __swallowed

        @exception_swallowed
        def sync():
            """Called on the instance sync intervals"""
            self._instance_sync_counter += 1

            # Check if it's time to do a full sync
            if self.full_instance_sync_required or (
                    self._instance_sync_counter == full_sync_frequency):
                self.full_instance_sync_required = False
                self._instance_sync_counter = 0
                LOG.debug(_('Syncing all instances on interval'))
                self._periodic_instance_sync(context)
                return

            # If there are no marked instances to sync stop here
            instance_ids = self.sync_instances.keys()
            if len(instance_ids) == 0:
                LOG.debug(_('No marked instances to sync.'))
                return

            LOG.debug(_('Syncing marked instances'))
            self._periodic_instance_sync(context, instance_ids=instance_ids)

        sync_call = loopingcall.FixedIntervalLoopingCall(sync)
        sync_call.start(interval=sync_interval, initial_delay=sync_interval)

        #
        # Start flavor sync.
        #
        flavor_interval = CONF.powervc.flavor_sync_interval
        if flavor_interval is None or flavor_interval == 0:
            return

        @exception_swallowed
        def sync_flavor():
            fl = flavorsync.FlavorSync(self.driver,
                                       self.scg_id_list)
            fl.synchronize_flavors(context)
        flavor_call = loopingcall.FixedIntervalLoopingCall(sync_flavor)
        flavor_call.start(interval=flavor_interval,
                          initial_delay=flavor_interval)

    def get_default_image(self, context):
        """
        The PowerVC Default Image is used when we can't figure out the actual
        image that originated an instance in PowerVC.

        We need to have an actual image reference in nova, because nova must
        have an image reference in order to show the instance details, else
        'nova show' will fail, so we create a generic image reference in Glance
        that all PowerVC instances for whom we don't know the originating
        image will use.
        """

        if self._default_image:
            return self._default_image

        glance_images = self._list_local_images(context)
        for glance_image in glance_images:
            if glance_image['name'] == CONF.powervc.powervc_default_image_name:
                self._default_image = glance_image
                return self._default_image

        # The default image has not been created, so let's do so
        LOG.info(_('Creating PowerVC Default Image in Glance repository'))
        image_data = {
            'is_public': True,
            'name': CONF.powervc.powervc_default_image_name,
            'disk_format': 'raw',
            'container_format': 'ovf',
            'protected': 'True',
            'properties': {
                'architecture':
                constants.PPC64,
                'hypervisor_type':
                constants.PVM_HYPERVISOR_TYPE
            }
        }
        self._default_image = \
            glance.get_default_image_service().create(context, image_data)
        return self._default_image

    def _fix_instance_nw_info(self, context, instance):
        """
           Fix instance network info if necessary.
        """
        if instance.get('info_cache'):
            network_info = instance.get('info_cache').get('network_info')
            # network_info is a stringnized empty array.
            if not network_info or network_info == u'[]':
                # Empty network_info, could be missing network_info
                search_opts = {'device_id': instance['uuid'],
                               'tenant_id': instance['project_id']}
                data = self.network_api.list_ports(context, **search_opts)
                ports = data.get('ports', [])
                # If ports is not empty, should put that into network_info.
                if ports:
                    nets = self.network_api.get_all(context)
                    # Call this will trigger info_cache update,
                    # which links instance with the port.
                    port_ids = []
                    for port in ports:
                        port_ids.append(port.get('id'))
                    nw_info = self.network_api.get_instance_nw_info(context,
                                                                    instance,
                                                                    nets,
                                                                    port_ids)
                    LOG.info("_fix_instance_nw_info" + str(nw_info))

    def _get_instance_root_device_name(self, pvc_instance, db_instance):
        root_device_name = '/dev/sda'
        if db_instance and db_instance.get('root_device_name'):
            LOG.info("root_device_name %s from local db"
                     % db_instance.get('root_device_name'))
            return db_instance.get('root_device_name')
        if not pvc_instance:
            LOG.info("set root_device_name as default: %s " % root_device_name)
            return root_device_name
        pvc_id = pvc_instance.get('id')
        if not pvc_id:
            LOG.info("set root_device_name as default: %s " % root_device_name)
            return root_device_name
        pvc_root_device_name = self.driver.get_pvc_root_device_name(pvc_id)
        if pvc_root_device_name:
            root_device_name = pvc_root_device_name
            LOG.info("set root_device_name as powervc boot volume device "
                     "name: %s " % root_device_name)
        return root_device_name
