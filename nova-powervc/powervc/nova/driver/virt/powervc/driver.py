# Copyright 2013, 2014 IBM Corp.
import nova
from novaclient.exceptions import NotFound
from novaclient.exceptions import BadRequest
from nova import exception
from nova.compute import task_states
from nova.image import glance
from nova.virt import driver
from oslo.serialization import jsonutils
from oslo_log import log as logging
from oslo.utils import excutils
from powervc.nova.driver.virt.powervc import service
from powervc.nova.driver.compute import constants
from powervc.nova.driver.virt.powervc import pvc_vm_states
from powervc.nova.common import exception as pvc_exception
from powervc.common.client import factory
from powervc.common.gettextutils import _
from powervc.common import constants as common_constants
from oslo.config import cfg
from powervc import utils as novautils
from nova import db
import socket

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

"""
A driver that connects to a PowerVC system.

"""


class PowerVCDriver(driver.ComputeDriver):
    """
    A nova-compute driver for PowerVC.

    This driver provides virtual machine management using IBM PowerVC
    hypervisor management software that is itself an openstack implementation.
    This driver requires that users provide the hostname, username and
    password for the target IBM PowerVC system.
    """
    nc = None
    cached_root_device_map = {}

    def __init__(self, virtapi):
        self.virtapi = virtapi
        self._compute_event_callback = None
        if(PowerVCDriver.nc is None):
            PowerVCDriver.nc = factory.POWERVC.new_client(
                str(common_constants.SERVICE_TYPES.compute))

        self._service = service.PowerVCService(PowerVCDriver.nc)
        self._stats = None

    def init_host(self, host):
        """Initialize anything that is necessary for the driver to function,
        including catching up with currently running VM's on the given host.
        """
        # Override the configuration host value for the virtual nova compute
        # instance so live migration will have the correct host value and not
        # the value defined in nova.conf. For details see
        # nova.compute.manager.check_can_live_migrate_destination
        CONF.host = host
        self.host = host
        # Initialize instance members for the powerVC hostname
        # and id.
        hypervisorlist = self._service.list_hypervisors()
        for hypervisor in hypervisorlist:
            if hypervisor._info["service"]["host"] == host:
                # Cache the hostname and hypervisor id
                self.hostname = hypervisor._info["hypervisor_hostname"]
                self.hypervisor_id = hypervisor._info["id"]
                break

    def _get_instance_by_uuid(self, ctxt, uuid):
        filters = {'uuid': uuid}
        db_matches = db.instance_get_all_by_filters(ctxt, filters)
        return db_matches

    def _get_pvcid_from_metadata(self, instance):
        """
        Because the data structure of the instance passed by
        the nova manager is different from normal structure,
        use this method to get the PowerVC id from the instance
        metadata
        """
        if not isinstance(instance, dict):
            instance = instance.__dict__
        metadata = instance.get('metadata')
        # In some cases, it's _metadata
        if metadata is None:
            metadata = instance.get('_metadata')

        LOG.debug(_("Got metadata: %s") % metadata)
        pvc_id = novautils.get_pvc_id_from_metadata(metadata)
        LOG.debug(_("Got pvc_id from _get_pvcid_from_metadata: %s") % pvc_id)
        return pvc_id

    def _int_or_none(self, value):
        try:
            return int(value)
        except Exception:
            return None

    def get_info(self, instance):
        """Get the current status of an instance, by name (not ID!)

        Returns a dict containing:

        :state:           the running state, one of the power_state codes
        :max_mem:         (int) the maximum memory in KBytes allowed
        :mem:             (int) the memory in KBytes used by the domain
        :num_cpu:         (int) the number of virtual CPUs for the domain
        :cpu_time:        (int) the CPU time used in nanoseconds
        """
        LOG.debug(_("get_info() Enter: %s" % str(instance)))
        lpar_instance = None
        try:
            pvc_id = self._get_pvcid_from_metadata(instance)
            if pvc_id is None:
                LOG.debug(_("Find pvc_id from DB"))
                ctx = nova.context.get_admin_context()
                db_instances = self._get_instance_by_uuid(ctx,
                                                          instance['uuid'])
                pvc_id = self._get_pvcid_from_metadata(db_instances[0])
            LOG.debug(_("pvc_id: %s" % str(pvc_id)))
            lpar_instance = self.get_instance(pvc_id)
            LOG.debug(_("Found instance: %s" % str(lpar_instance)))
        except Exception:
            if pvc_id is None:
                LOG.info(_("Can not get the pvc_id from the"
                           " instance %s." % instance['name']))
            else:
                LOG.info(_("Can not get the PowerVC"
                           " instance %s." % pvc_id))
            raise exception.NotFound

        if(lpar_instance is None):
            LOG.info(_("Can not get the PowerVC"
                       " instance %s." % pvc_id))
            raise exception.NotFound

        LOG.debug(_("get_info() Exit"))
        max_mem = self._int_or_none(lpar_instance._info.get('max_memory_mb'))
        mem = self._int_or_none(lpar_instance._info.get('memory_mb'))
        num_cpu = self._int_or_none(lpar_instance._info.get('cpus'))
        hardwareInfo = pvc_vm_states.InstanceInfo(
            state=lpar_instance._info['OS-EXT-STS:power_state'],
            max_mem_kb=max_mem,
            mem_kb=mem,
            num_cpu=num_cpu)
        return hardwareInfo

    def get_num_instances(self):
        """Return the total number of virtual machines.

        Return the number of virtual machines that the hypervisor knows
        about.

        .. note::

            This implementation works for all drivers, but it is
            not particularly efficient. Maintainers of the virt drivers are
            encouraged to override this method with something more
            efficient.
        """
        return len(self.list_instances())

    def list_instances(self):
        """
        Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        return self._service.list_instances()

    def list_instance_uuids(self):
        """
        Return the UUIDS of all the instances known to the virtualization
        layer, as a list.
        """
        servers = self.list_instances()
        uuids = []
        for server in servers:
            uuids.append(server.id)
        return uuids

    def get_instance(self, instance_id):
        """
        Get the instance with the given id or None if not found.
        """
        instance = None
        try:
            instance = self._service.get_instance(instance_id)
        except NotFound:
            pass
        return instance

    def list_flavors(self):
        """
        Return the names of all the flavors known to the virtualization
        layer, as a list.
        """
        return self._service.list_flavors()

    def get_flavor_extraspecs(self, flavor):
        """
        Return the extraspecs defined for a flavor as a dict.
        """
        return self._service.get_flavor_extraspecs(flavor)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              **kwargs):
        """
        Create a new instance/VM/domain on the virtualization platform.

        Once this successfully completes, the instance should be
        running (power_state.RUNNING).

        If this fails, any partial instance should be completely
        cleaned up, and the virtualization platform should be in the state
        that it was before this call began.

        :param context: security context
        :param instance: Instance object as returned by DB layer.
                         This function should use the data there to guide
                         the creation of the new instance.
        :param image_meta: image object returned by nova.image.glance that
                           defines the image from which to boot this instance
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in instance.
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param block_device_info: Information about block devices to be
                                  attached to the instance.
        """
        LOG.info(_("Begin to deploy the instance %(uuid)s") % instance)
        # get PowerVC Image id
        pvcimage = self._get_pvc_image_uuid(image_meta)

        # get PowerVC Flavor
        pvcflavor = self._get_pvc_flavor(context, instance)

        # check if the host selection will be defer to PowerVC
        isDefer = self._check_defer_placement(instance)

        # If hosting OS decide to select one host,
        # get the PowerVC Hypervisor host name
        # else the host name will be ignore
        pvcHypervisor = None
        pvcAvailabilityZone = None
        if not isDefer:
            # When targetting a compute node, uses the cached
            # powervc hypervisor id that this nova compute service
            # represents, it will be the same.
            pvcHypervisor = self.hypervisor_id
            pvcAvailabilityZone = self._get_pvc_avalability_zone(instance)

        # get PowerVC network info
        pvc_nics = self._get_pvc_network_info(context, network_info)
        LOG.debug("Spwan instance with NICs: %s" % pvc_nics)

        LOG.debug("Instance to spawn: %s" % instance)
        createdServer = None
        try:
            createdServer = \
                self._service.spawn(context=context,
                                    instance=instance,
                                    injected_files=injected_files,
                                    name=instance['hostname'],
                                    imageUUID=pvcimage,
                                    flavorDict=pvcflavor,
                                    nics=pvc_nics,
                                    hypervisorID=pvcHypervisor,
                                    availability_zone=pvcAvailabilityZone,
                                    isDefer=isDefer)
        except BadRequest as e1:
            with excutils.save_and_reraise_exception():
                self._clean_vm_and_save_fault_message(e1, e1.message,
                                                      context, instance)
        except exception.InstanceInvalidState as e2:
            with excutils.save_and_reraise_exception():
                self._clean_vm_and_save_fault_message(e2, e2.message,
                                                      context, instance)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                self._clean_vm_and_save_fault_message(e, e.message,
                                                      context, instance)

        LOG.info("Finish to create the instance to spawn: %s successfully"
                 % createdServer)
        return createdServer

    def _clean_vm_and_save_fault_message(self, exp, message, context,
                                         instance):
        """
        This method does the following things when exception thrown in spawn:
        1. log powervc side error message to hosting os fault property
        2. destroy vm in powerVC with pvc_id set in instance
        3. remove pvc_id from local vm
        """
        LOG.warning("Created instance failed: %s" % message)

        # To log powervc side error message to hosting os fault property,
        # raise an InstanceDeployFailure with powervc error message set
        # and the framework will help to set the error message to hosting os
        # fault property
        # But by now openstack framework still has an issue to prevent this:
        # https://bugs.launchpad.net/nova/+bug/1161661
        # To workaround this, just do the follow step and the powervc error
        # can be shown on hosting os vm instance:
        # 1. Set scheduler_max_attempts=1 in /etc/nova/nova.conf
        # 2. Restart openstack-nova-scheduler service

        # destory vm in pvc side
        try:
            self.destroy(None, instance, None)
        except Exception as e:
            # Ignore the exception in destroy()
            LOG.warning("Destroy instance throw exception: %s" % e.message)
        meta = instance.get('metadata')
        if not meta:
            LOG.warning("No metadata for instance: %s", instance)
            return
        # remove pvc_id
        if constants.PVC_ID in meta.keys():
            del(meta[constants.PVC_ID])
        instance['metadata'] = meta
        # remove activation engine configuration_data as db is not allowed
        instance.system_metadata.pop('configuration_data', None)
        instance.save()
        LOG.debug('Saved instance with clearing pvc_id in metadata during'
                  'spawn failure: %s', instance)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy (shutdown and delete) the specified instance.

        If the instance is not found (for example if networking failed), this
        function should still succeed.  It's probably a good idea to log a
        warning in that case.

        :param instance: Instance object as returned by DB layer.
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param block_device_info: Information about block devices that should
                                  be detached from the instance.
        :param destroy_disks: Indicates if disks should be destroyed

        """
        LOG.debug(_("Enter to destroy instance of %(uuid)s") % instance)
        responseValue = self._service.destroy(instance)
        LOG.debug(_("Exit to destroy instance of %(uuid)s") % instance)
        return responseValue

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot the specified instance.

        After this is called successfully, the instance's state
        goes back to power_state.RUNNING. The virtualization
        platform should ensure that the reboot action has completed
        successfully even in cases in which the underlying domain/vm
        is paused or halted/stopped.

        :param instance: nova.objects.instance.Instance
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param reboot_type: Either a HARD or SOFT reboot
        :param block_device_info: Info pertaining to attached volumes
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered
        """
        return self._service.reboot(instance, reboot_type)

    def get_console_pool_info(self, *args, **kwargs):
        raise NotImplementedError()

    def get_console_output(self, *args, **kwargs):
        raise NotImplementedError()

    def get_vnc_console(self, *args, **kwargs):
        raise NotImplementedError()

    def get_spice_console(self, *args, **kwargs):
        raise NotImplementedError()

    def get_diagnostics(self, *args, **kwargs):
        """Return data about VM diagnostics."""
        raise NotImplementedError()

    def get_all_bw_counters(self, *args, **kwargs):
        """Return bandwidth usage counters for each interface on each
           running VM.
        """
        raise NotImplementedError()

    def get_all_volume_usage(self, *args, **kwargs):
        """Return usage info for volumes attached to vms on
           a given host.-
        """
        raise NotImplementedError()

    def get_host_ip_addr(self):
        """
        Retrieves the IP address of the dom0
        """
        default_value = '127.0.0.1'
        host_ip = CONF.my_ip
        if not host_ip:
            host_ip = self._get_local_ips()[0]
        if host_ip:
            return host_ip
        else:
            return default_value

    def _get_local_ips(self):
        """
        Retrieves all the IP addresses of the host machine
        """
        addr_info = socket.getaddrinfo(socket.gethostname(), None, 0, 0, 0)
        # Returns IPv4 and IPv6 addresses, ordered by protocol family
        addr_info.sort()
        index = 0
        host_ips = []
        for one_addr_info in addr_info:
            # the data structure of addr_info returned by the method
            # getaddrinfo is (family, socktype, proto, canonname, sockaddr).
            # Fox example:
            # (2, 1, 6, '', ('82.94.164.162', 80))
            # (10, 1, 6, '', ('2001:888:2000:d::a2', 80, 0, 0))
            host_ips[index] = one_addr_info[4][0]
            index = index + 1
        return host_ips

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the disk to the instance at mountpoint using info."""
        return self._service.attach_volume(connection_info, instance,
                                           mountpoint)

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the disk attached to the instance."""
        return self._service.detach_volume(connection_info, instance,
                                           mountpoint)

    def list_os_attachments(self, server_id):
        """List the volumes attached to the specified instance."""
        return self._service.list_os_attachments(server_id)

    def attach_interface(self, instance, image_meta, vif):
        """Attach an interface to the instance.
        """
        LOG.debug(_('enter PowerVC driver attach_interface for instance %s'
                    ' with vif info as %s'), instance, vif)
        context = nova.context.get_admin_context()
        try:
            server_id = instance.get('uuid')
            LOG.debug(_("Local Server uuid: %s") % server_id)

            port_id, network_id, ipAddress = self.\
                _get_port_network_ipaddress_from_vif(vif)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_("attach interface failed with wrong paras: %s"),
                          e, instance=instance)

        # call service to attach interface
        self._service.attach_interface(context,
                                       instance,
                                       port_id,
                                       network_id,
                                       ipAddress)
        LOG.debug(_('exit PowerVC driver attach_interface for instance %s'
                    ' with vif info as %s'), instance, vif)

    def _get_port_network_ipaddress_from_vif(self, vif):
        """Get port uuid, network uuid, and ip Address from vif
        """
        local_network_id = ''
        ipAddress = ''

        local_port_id = vif.get('id')
        local_network = vif.get('network')
        if local_network:
            local_network_id = local_network.get('id')
            local_subnet = local_network.get('subnets')
            if local_subnet and local_subnet[0]:
                ipAddresses = local_subnet[0].get('ips')
                if ipAddresses and ipAddresses[0]:
                    ipAddress = ipAddresses[0].get('address')

        LOG.debug(_("Local port uuid: %s") % local_port_id)
        LOG.debug(_("Local network uuid: %s") % local_network_id)
        LOG.debug(_("ip address: %s") % ipAddress)
        return (local_port_id, local_network_id, ipAddress)

    def detach_interface(self, instance, vif):
        """
        Detach an interface from the instance.
        This method is called AFTER nova compute manager deleted local port.
        """
        LOG.debug(_('enter PowerVC driver detach_interface for instance %s'
                    ' with vif info as %s'), instance, vif)
        context = nova.context.get_admin_context()
        # call service to detach interface
        self._service.detach_interface(context,
                                       instance,
                                       vif)
        LOG.debug(_('exit PowerVC driver detach_interface for instance %s'
                    ' with vif info as %s'), instance, vif)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        """
        This method is called at the beginning of a resize instance request.
        The sequence for resize operations is the following:
        1) User requests an instance resize to a new flavor
        2) Compute manager calls the driver.migrate_disk_and_power_off()
        3) Compute manager calls the driver.finish_migration()
        4) User can either confirm or revert the resize
        5) If confirmed, driver.confirm_migration() is called
        6) If reverted, driver.finish_revert_migration() is called
        Transfers the disk of a running instance in multiple phases, turning
        off the instance before the end.
        """
        # TODO: add support for timeout
        LOG.debug(_("The method migrate_disk_and_power_off is invoked."))
        """
        In order to support the live resize in the PowerVC, remove the
        power-off operation.
        """

    def snapshot(self, context, instance, image_id, update_task_state):
        """ Capture an image of an instance
        :param context: the context for the capture
        :param instance:  the instance to be capture
        :param image_id: the id of the local image created for the snapshot
        :param update_task_state: function for updating task state callback

        This function will cause the instance on the powervc server to be
        captured resulting in a new instance there.  Synchronization of
        between the local, hosting OS image and the powervc image will happen
        through the glance driver
        """
        image = glance.get_default_image_service().show(context, image_id)
        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)
        self._service.snapshot(context, instance,
                               image_id, image)
        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        """Completes a resize.

        :param context: the context for the migration/resize
        :param migration: the migrate/resize information
        :param instance: the instance being migrated/resized
        :param disk_info: the newly transferred disk information
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param image_meta: image object returned by nova.image.glance that
                           defines the image from which this instance
                           was created
        :param resize_instance: True if the instance is being resized,
                                False otherwise
        :param block_device_info: instance volume block device info
        :param power_on: True if the instance should be powered on, False
                         otherwise
        """
        LOG.debug(_("Enter to resize instance of %(uuid)s") % instance)
        returnvalue = False

        if resize_instance:
            LOG.debug(_("Begin to resize the instance."))
            returnvalue = self._service.resize_instance(context, migration,
                                                        instance,
                                                        image_meta)
            # Support the auto-confirm
            self.confirm_migration(None, instance, None)
            # Handle with updating the correct host
            self._service.update_correct_host(context, instance)

        else:
            # TODO if want to implement the cold migration, we can add
            # the corresponding code in this branch.
            LOG.debug(_("The cold migration has not been implemented."))
            raise NotImplementedError()
        """
        The PowerVC driver can support the live resize now. Do not need to
        start the instance directly.
        Based on the above reason, remove the 'power-on' operation.
        """
        LOG.debug(_("Exit to resize instance of %(uuid)s") % instance)
        return returnvalue

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        LOG.debug(_("Confirm a resize operation."))
        return self._service.confirm_migration(instance)

    def finish_revert_migration(self, *args, **kwargs):
        """
        Finish reverting a resize.

        :param instance: the instance being migrated/resized
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param block_device_info: instance volume block device info
        :param power_on: True if the instance should be powered on, False
                         otherwise
        """
        raise NotImplementedError()

    def pause(self, *args, **kwargs):
        """Pause the specified instance."""
        raise NotImplementedError()

    def unpause(self, *args, **kwargs):
        """Unpause paused VM instance."""
        raise NotImplementedError()

    def suspend(self, *args, **kwargs):
        """suspend the specified instance."""
        raise NotImplementedError()

    def resume(self, *args, **kwargs):
        """resume the specified instance."""
        raise NotImplementedError()

    def resume_state_on_host_boot(self, *args, **kwargs):
        """resume guest state when a host is booted."""
        raise NotImplementedError()

    def rescue(self, *args, **kwargs):
        """Rescue the specified instance."""
        raise NotImplementedError()

    def unrescue(self, *args, **kwargs):
        """Unrescue the specified instance."""
        raise NotImplementedError()

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance."""
        # TODO: add timeout support
        return self._service.power_off(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        return self._service.power_on(instance)

    def soft_delete(self, *args, **kwargs):
        """Soft delete the specified instance."""
        raise NotImplementedError()

    def restore(self, *args, **kwargs):
        """Restore the specified instance."""
        raise NotImplementedError()

    def get_available_nodes(self, refresh=False):
        """Returns nodenames of all nodes managed by the compute service.

        This method is for multi compute-nodes support. If a driver supports
        multi compute-nodes, this method returns a list of nodenames managed
        by the service. Otherwise, this method should return
        [hypervisor_hostname].
        """
        stats = self.get_host_stats(refresh=refresh)
        if not isinstance(stats, list):
            stats = [stats]
        return [s['hypervisor_hostname'] for s in stats]

    def get_available_resource(self, *args, **kwargs):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task

        :param nodename:
            node which the caller want to get resources from
            a driver that manages only one node can safely ignore this
        :returns: Dictionary describing resources
        """
        return self._update_status()

    def _get_cpu_info(self):
        """Get cpuinfo information.

        """

        cpu_info = dict()

        cpu_info['arch'] = 'ppc64'
        cpu_info['model'] = 'powervc'
        cpu_info['vendor'] = 'IBM'

        topology = dict()
        topology['sockets'] = '1'
        topology['cores'] = '1'
        topology['threads'] = '1'
        cpu_info['topology'] = topology

        features = list()
        cpu_info['features'] = features

        return jsonutils.dumps(cpu_info)

    def pre_live_migration(self, ctxt, instance_ref,
                           block_device_info, network_info, disk,
                           migrate_data=None):
        """Prepare an instance for live migration

        :param ctxt: security context
        :param instance_ref: instance object that will be migrated
        :param block_device_info: instance block device information
        :param network_info: instance network information
        :param disk: Instance disk information, if doing block migration
        :param migrate_data: implementation specific data dict.
        """

        # Get the latest instance information from powervc and
        # validate its safe to request a live migration.
        meta = instance_ref.get('metadata')
        lpar_instance = self.get_instance(meta['pvc_id'])

        if lpar_instance is None:
            reason = (_("Unable to migrate uuid:%s."
                        "Unable to retrieve powerVC instance.")
                      % instance_ref['uuid'])
            raise exception.MigrationPreCheckError(reason=reason)

        server_dict = lpar_instance.__dict__
        valid = (self._service._is_live_migration_valid(
                 server_dict['status'], server_dict['health_status']))
        if not valid:
            reason = (_("Unable to migrate uuid:%s ."
                        "PowerVC validation failed, please verify instance "
                        "is active and health status is OK. "
                        "If the RMC connection to the HMC is not active, live "
                        "migration can not be attempted.")
                      % instance_ref['uuid'])
            raise exception.MigrationPreCheckError(reason=reason)

        return {}

    def pre_block_migration(self, *args, **kwargs):
        """Prepare a block device for migration

        :param ctxt: security context
        :param instance_ref: instance object that will have its disk migrated
        :param disk_info: information about disk to be migrated (as returned
                          from get_instance_disk_info())
        """
        raise pvc_exception.BlockMigrationException()

    def live_migration(self, ctxt, instance_ref, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Live migration of an instance to another host.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params dest: destination host
        :params post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :params recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.
        :params block_migration: if true, migrate VM disk.
        :params migrate_data: implementation specific params.

        """
        isDefer = self._check_defer_placement(instance_ref)
        if isDefer:
            dest = None
        try:
            self._service.live_migrate(instance_ref, dest, migrate_data)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Live Migration failure: %s"), e,
                          instance=instance_ref)
                recover_method(ctxt, instance_ref, dest, block_migration,
                               migrate_data)

        post_method(ctxt, instance_ref, dest, block_migration, migrate_data)

    def post_live_migration_at_destination(self, *args, **kwargs):
        """Post operation of live migration at destination host.

        :param ctxt: security context
        :param instance_ref: instance object that is migrated
        :param network_info: instance network information
        :param block_migration: if true, post operation of block_migration.
        """
        pass

    def check_instance_shared_storage_local(self, *args, **kwargs):
        """Check if instance files located on shared storage.

        This runs check on the destination host, and then calls
        back to the source host to check the results.

        :param ctxt: security context
        :param instance: nova.db.sqlalchemy.models.Instance
        """
        raise NotImplementedError()

    def check_instance_shared_storage_remote(self, *args, **kwargs):
        """Check if instance files located on shared storage.

        :param context: security context
        :param data: result of check_instance_shared_storage_local
        """
        raise NotImplementedError()

    def check_instance_shared_storage_cleanup(self, *args, **kwargs):
        """Do cleanup on host after check_instance_shared_storage calls

        :param ctxt: security context
        :param data: result of check_instance_shared_storage_local
        """
        pass

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param ctxt: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance
        :param src_compute_info: Info about the sending machine
        :param dst_compute_info: Info about the receiving machine
        :param block_migration: if true, prepare for block migration
        :param disk_over_commit: if true, allow disk over commit
        :returns: a dict containing migration info (hypervisor-dependent)
        """
        # Remove the corresponding source codes for the nova component
        # does not catch the exceptions thrown by this method and do
        # the corresponding roll back operations.

        # PowerVC driver does not support block migration or disk over
        # commit. Let our callers know with failure.
        if block_migration:
            reason = (_("Unable to migrate uuid:%s to host %s: "
                        "Block Migration not supported")
                      % (instance_ref['uuid'],
                         dst_compute_info['hypervisor_hostname']))
            raise exception.MigrationPreCheckError(reason=reason)

        if disk_over_commit:
            reason = (_("Unable to migrate uuid:%s to host %s: "
                        "Disk Over Commit not supported")
                      % (instance_ref['uuid'],
                         dst_compute_info['hypervisor_hostname']))
            raise exception.MigrationPreCheckError(reason=reason)

        # check if the host selection will be defer to PowerVC
        isDefer = self._check_defer_placement(instance_ref)
        if not isDefer:
            valid_hosts = self._service.get_valid_destinations(instance_ref)
            LOG.debug('compute manager host is %s, valid destination hosts '
                      'are %s', CONF.host, valid_hosts)
            for key in valid_hosts:
                if key == CONF.host:
                    return dst_compute_info
            msg = (_('Destination host %s for live migration is invalid'
                     ' following powervc validation check for the instance %s')
                   % (dst_compute_info, instance_ref))
            raise exception.Invalid(msg)
        else:
            return dst_compute_info

    def check_can_live_migrate_destination_cleanup(self, *args, **kwargs):
        """Do required cleanup on dest host after check_can_live_migrate calls

        :param ctxt: security context
        :param dest_check_data: result of check_can_live_migrate_destination
        """
        pass

    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance
        :param dest_check_data: result of check_can_live_migrate_destination
        :returns: a dict containing migration info (hypervisor-dependent)
        """
        return dest_check_data

    def refresh_security_group_rules(self, *args, **kwargs):
        """This method is called after a change to security groups.

        All security groups and their associated rules live in the datastore,
        and calling this method should apply the updated rules to instances
        running the specified security group.

        An error should be raised if the operation cannot complete.

        """
        raise NotImplementedError()

    def refresh_security_group_members(self, *args, **kwargs):
        """This method is called when a security group is added to an instance.

        This message is sent to the virtualization drivers on hosts that are
        running an instance that belongs to a security group that has a rule
        that references the security group identified by `security_group_id`.
        It is the responsibility of this method to make sure any rules
        that authorize traffic flow with members of the security group are
        updated and any new members can communicate, and any removed members
        cannot.

        Scenario:
            * we are running on host 'H0' and we have an instance 'i-0'.
            * instance 'i-0' is a member of security group 'speaks-b'
            * group 'speaks-b' has an ingress rule that authorizes group 'b'
            * another host 'H1' runs an instance 'i-1'
            * instance 'i-1' is a member of security group 'b'

            When 'i-1' launches or terminates we will receive the message
            to update members of group 'b', at which time we will make
            any changes needed to the rules for instance 'i-0' to allow
            or deny traffic coming from 'i-1', depending on if it is being
            added or removed from the group.

        In this scenario, 'i-1' could just as easily have been running on our
        host 'H0' and this method would still have been called.  The point was
        that this method isn't called on the host where instances of that
        group are running (as is the case with
        :py:meth:`refresh_security_group_rules`) but is called where references
        are made to authorizing those instances.

        An error should be raised if the operation cannot complete.

        """
        raise NotImplementedError()

    def refresh_provider_fw_rules(self, *args, **kwargs):
        """This triggers a firewall update based on database changes.

        When this is called, rules have either been added or removed from the
        datastore.  You can retrieve rules with
        :py:meth:`nova.db.provider_fw_rule_get_all`.

        Provider rules take precedence over security group rules.  If an IP
        would be allowed by a security group ingress rule, but blocked by
        a provider rule, then packets from the IP are dropped.  This includes
        intra-project traffic in the case of the allow_project_net_traffic
        flag for the libvirt-derived classes.

        """
        raise NotImplementedError()

    def reset_network(self, *args, **kwargs):
        """reset networking for specified instance."""
        pass

    def ensure_filtering_rules_for_instance(self, *args, **kwargs):
        """Setting up filtering rules and waiting for its completion.

        To migrate an instance, filtering rules to hypervisors
        and firewalls are inevitable on destination host.
        ( Waiting only for filtering rules to hypervisor,
        since filtering rules to firewall rules can be set faster).

        Concretely, the below method must be called.
        - setup_basic_filtering (for nova-basic, etc.)
        - prepare_instance_filter(for nova-instance-instance-xxx, etc.)

        to_xml may have to be called since it defines PROJNET, PROJMASK.
        but libvirt migrates those value through migrateToURI(),
        so , no need to be called.

        Don't use thread for this method since migration should
        not be started when setting-up filtering rules operations
        are not completed.

        :params instance_ref: nova.db.sqlalchemy.models.Instance object

        """
        pass

    def filter_defer_apply_on(self, *args, **kwargs):
        """Defer application of IPTables rules."""
        pass

    def filter_defer_apply_off(self, *args, **kwargs):
        """Turn off deferral of IPTables rules and apply the rules now."""
        pass

    def unfilter_instance(self, *args, **kwargs):
        """Stop filtering instance."""
        pass

    def set_admin_password(self, *args, **kwargs):
        """
        Set the root password on the specified instance.

        The first parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name. The second
        parameter is the value of the new password.
        """
        raise NotImplementedError()

    def inject_file(self, *args, **kwargs):
        """
        Writes a file on the specified instance.

        The first parameter is an instance of nova.compute.service.Instance,
        and so the instance is being specified as instance.name. The second
        parameter is the base64-encoded path to which the file is to be
        written on the instance; the third is the contents of the file, also
        base64-encoded.
        """
        raise NotImplementedError()

    def change_instance_metadata(self, *args, **kwargs):
        """
        Applies a diff to the instance metadata.

        This is an optional driver method which is used to publish
        changes to the instance's metadata to the hypervisor.  If the
        hypervisor has no means of publishing the instance metadata to
        the instance, then this method should not be implemented.
        """
        pass

    def inject_network_info(self, *args, **kwargs):
        """inject network info for specified instance."""
        pass

    def poll_rebooting_instances(self, *args, **kwargs):
        """Poll for rebooting instances

        :param timeout: the currently configured timeout for considering
                        rebooting instances to be stuck
        :param instances: instances that have been in rebooting state
                          longer than the configured timeout
        """
        raise NotImplementedError()

    def host_power_action(self, *args, **kwargs):
        """Reboots, shuts down or powers up the host."""
        raise NotImplementedError()

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        try:
            self._service.set_host_maintenance_mode(host, mode)
        except Exception as e:
            # return powervc error message to uplayer
            LOG.error(_("Set host maintenance mode failed: %s"), e)
            return e.message
        # return 'on_maintenance' or 'off_maintenance' string
        # to nova-api response if pvc performed with no Exception
        if mode:
            return 'on_maintenance'
        else:
            return 'off_maintenance'

    def set_host_enabled(self, *args, **kwargs):
        """Sets the specified host's ability to accept new instances."""
        raise NotImplementedError()

    def get_host_uptime(self, *args, **kwargs):
        """Returns the result of calling "uptime" on the target host."""
        raise NotImplementedError()

    def plug_vifs(self, *args, **kwargs):
        """Plug VIFs into networks."""
        # TODO: this is hardcoded
        pass

    def unplug_vifs(self, *args, **kwargs):
        """Unplug VIFs from networks."""
        # TODO: this is hardcoded
        pass

    def get_host_stats(self, refresh=False):
        """Return the current state of the host.

        If 'refresh' is True, run update the stats first.
        """
        if refresh or self._stats is None:
            self._update_status()
        return self._stats

    def node_is_available(self, nodename):
        """Return that a given node is known and available."""
        return nodename in self.get_available_nodes(refresh=True)

    def block_stats(self, *args, **kwargs):
        """
        Return performance counters associated with the given disk_id on the
        given instance_name.  These are returned as [rd_req, rd_bytes, wr_req,
        wr_bytes, errs], where rd indicates read, wr indicates write, req is
        the total number of I/O requests made, bytes is the total number of
        bytes transferred, and errs is the number of requests held up due to a
        full pipeline.

        All counters are long integers.

        This method is optional.  On some platforms (e.g. XenAPI) performance
        statistics can be retrieved directly in aggregate form, without Nova
        having to do the aggregation.  On those platforms, this method is
        unused.

        Note that this function takes an instance ID.
        """
        raise NotImplementedError()

    def interface_stats(self, *args, **kwargs):
        """
        Return performance counters associated with the given iface_id on the
        given instance_id.  These are returned as [rx_bytes, rx_packets,
        rx_errs, rx_drop, tx_bytes, tx_packets, tx_errs, tx_drop], where rx
        indicates receive, tx indicates transmit, bytes and packets indicate
        the total number of bytes or packets transferred, and errs and dropped
        is the total number of packets failed / dropped.

        All counters are long integers.

        This method is optional.  On some platforms (e.g. XenAPI) performance
        statistics can be retrieved directly in aggregate form, without Nova
        having to do the aggregation.  On those platforms, this method is
        unused.

        Note that this function takes an instance ID.
        """
        raise NotImplementedError()

    def legacy_nwinfo(self, *args, **kwargs):
        """True if the driver requires the legacy network_info format."""
        return False

    def macs_for_instance(self, *args, **kwargs):
        """What MAC addresses must this instance have?

        Some hypervisors (such as bare metal) cannot do freeform virtualisation
        of MAC addresses. This method allows drivers to return a set of MAC
        addresses that the instance is to have. allocate_for_instance will take
        this into consideration when provisioning networking for the instance.

        Mapping of MAC addresses to actual networks (or permitting them to be
        freeform) is up to the network implementation layer. For instance,
        with openflow switches, fixed MAC addresses can still be virtualised
        onto any L2 domain, with arbitrary VLANs etc, but regular switches
        require pre-configured MAC->network mappings that will match the
        actual configuration.

        Most hypervisors can use the default implementation which returns None.
        Hypervisors with MAC limits should return a set of MAC addresses, which
        will be supplied to the allocate_for_instance call by the compute
        manager, and it is up to that call to ensure that all assigned network
        details are compatible with the set of MAC addresses.

        This is called during spawn_instance by the compute manager.

        :return: None, or a set of MAC ids (e.g. set(['12:34:56:78:90:ab'])).
            None means 'no constraints', a set means 'these and only these
            MAC addresses'.
        """
        return None

    def manage_image_cache(self, *args, **kwargs):
        """
        Manage the driver's local image cache.

        Some drivers chose to cache images for instances on disk. This method
        is an opportunity to do management of that cache which isn't directly
        related to other calls into the driver. The prime example is to clean
        the cache and remove images which are no longer of interest.
        """
        pass

    def add_to_aggregate(self, *args, **kwargs):
        """Add a compute host to an aggregate."""
        pass

    def remove_from_aggregate(self, *args, **kwargs):
        """Remove a compute host from an aggregate."""
        pass

    def undo_aggregate_operation(self, *args, **kwargs):
        """Undo for Resource Pools."""
        raise NotImplementedError()

    def get_volume_connector(self, *args, **kwargs):
        """Get connector information for the instance for attaching to volumes.

        Connector information is a dictionary representing the ip of the
        machine that will be making the connection, the name of the iscsi
        initiator and the hostname of the machine as follows::

            {
                'ip': ip,
                'initiator': initiator,
                'host': hostname
            }

        The PowerVC will only support FC volume. The connector information
        as follow
            {
                'host': hostname
                'wwpns': WWPNs
            }
        The PowerVC driver may not check the connection of the volume. It can
        use the result of the attach REST API from the PowerVC to determine
        whether the attach operation is successful.
        """

        return {
            'ip': '127.0.0.1',
            'host': 'hostname'
        }

    def get_per_instance_usage(self, *args, **kwargs):
        """Get information about instance resource usage.

        :returns: dict of  nova uuid => dict of usage info
        """
        # TODO: This is hardcoded
        return {}

    def instance_on_disk(self, *args, **kwargs):
        """Checks access of instance files on the host.

        :param instance: instance to lookup

        Returns True if files of an instance with the supplied ID accessible on
        the host, False otherwise.

        .. note::
            Used in rebuild for HA implementation and required for validation
            of access to instance shared disk files
        """
        return False

    def register_event_listener(self, callback):
        """Register a callback to receive events.

        Register a callback to receive asynchronous event
        notifications from hypervisors. The callback will
        be invoked with a single parameter, which will be
        an instance of the nova.virt.event.Event class.
        """

        self._compute_event_callback = callback

    def list_images(self):
        """Return the names of all the images known to the virtualization
        layer, as a list.
        """
        return self._service.list_images()

    def get_hypervisor_by_hostname(self, hostname):
        """Return the information of the specified hypervisors
        by the given hostname
        """
        if self.hostname:
            return self._service.get_hypervisor(self.hypervisor_id)

        # (Re)Initialize the cache
        hypervisorlist = self._service.list_hypervisors()
        for hypervisor in hypervisorlist:
            if hypervisor._info["service"]["host"] == self.host:
                # Cache the hostname and hypervisor id
                self.hostname = hypervisor._info["hypervisor_hostname"]
                self.hypervisor_id = hypervisor._info["id"]

        return self._service.get_hypervisor(self.hypervisor_id)

    def _update_status(self):
        """Retrieve status info from PowerVC."""
        LOG.debug(_("Updating host stats"))
        hypervisor = self.get_hypervisor_by_hostname(self.hostname)
        if hypervisor is None:
            return None
        info = hypervisor._info

        local_gb = info["local_gb"]
        if 0 == int(local_gb):
            local_gb = info["local_gb_used"]
        # avoid value too large to damage the hosting os
        m_size = CONF.powervc.max_host_disk_size
        local_gb = m_size if local_gb > m_size else local_gb
        disk_available_least = info["disk_available_least"]
        disk_available_least = m_size if disk_available_least > m_size else\
            disk_available_least

        vcpus = int(float(info["vcpus"]) - float(info["proc_units_reserved"]))
        memory_mb = int(info["memory_mb"]) - int(info["memory_mb_reserved"])
        used_memory = info.get("memory_mb_used") or\
            (memory_mb - int(info.get("free_ram_mb")))

        data = {'vcpus': vcpus,
                'vcpus_used': info["vcpus_used"],
                'memory_mb': memory_mb,
                'memory_mb_used': used_memory,
                'local_gb': local_gb,
                'local_gb_used': info["local_gb_used"],
                'disk_available_least': disk_available_least,
                'hypervisor_hostname': info["hypervisor_hostname"],
                'hypervisor_type': info["hypervisor_type"],
                'hypervisor_version': info["hypervisor_version"],
                'cpu_info': info["cpu_info"],
                'supported_instances': jsonutils.dumps(
                    constants.POWERVC_SUPPORTED_INSTANCES)}

        self._stats = data
        return data

    def _get_pvc_image_uuid(self, image_meta):
        """
        Get powerVC image UUID from local image instance property that is
        synchronized from PowerVC image
        """
        pvcImageUUID = None

        if image_meta['deleted']:
            raise exception.ImageNotActive(image_id=image_meta['id'])

        # PowerVC image UUID will be saved in image_meta as
        # property when image synchronization finished.
        if image_meta['properties']:
            pvcImageUUID = image_meta['properties']['powervc_uuid']
            LOG.debug("ImageUUID on powervc: %s" % pvcImageUUID)

        # raise exception if pvcImageUUID not found
        if not pvcImageUUID:
            raise exception.ImageNotFound(image_id=image_meta['name'])
        return pvcImageUUID

    def _get_pvc_flavor(self, context, instance):
        """
        Fill flavor detail from instance info into dic, this dic will be
        passed into _boot() method to generate the flavor info to
        PowerVC later
        """
        # get flavor from DB
        flavor_id = instance['instance_type_id']
        flavor = db.flavor_get(context, flavor_id)
        return flavor

    def _get_pvc_network_info(self, context, network_info):
        """
        Create the network info list which is used to fill in
        the body of the REST request from local network
        synchronized from PowerVC network
        """

        networks = []

        for network_info_iter in network_info:

            network = dict()

            # Get the PowerVC network id
            one_network_info = network_info_iter.get('network')
            if one_network_info is None:
                continue
            local_id = one_network_info.get('id')
            if local_id is None:
                continue
            # the 'net-id' will be changed to the 'uuid' in the boot method
            pvc_id = self._service.get_pvc_network_uuid(context, local_id)
            if pvc_id is None:
                # 167976 abort the boot, if not found pvc network
                raise exception.NetworkNotFoundForUUID(uuid=str(local_id))

            network['net-id'] = pvc_id

            # map the local port id to PowerVC port id
            local_port_id = network_info_iter.get('id')
            pvc_port_id = self._service.get_pvc_port_uuid(context,
                                                          local_port_id)
            if pvc_port_id:
                network['port-id'] = pvc_port_id

            # The v4-fixed-ip will be changed to the fixed-ip in the boot
            # method
            subnets = one_network_info.get('subnets')
            if subnets is None:
                networks.append(network)
                continue
            for subnet_iter in subnets:
                ips = subnet_iter.get('ips')
                if ips is None:
                    continue
                for ip_iter in ips:
                    ipaddress = ip_iter.get('address')
                    if ipaddress is None:
                        continue
                    network['v4-fixed-ip'] = ipaddress

            networks.append(network)

        return networks

    def _get_pvc_avalability_zone(self, instance):
        """
        Return the availability zone constructed for the specified host
        """
        # TODO: Need to revisit this method after confirmation with powervc
        return ':' + instance['host']

    def _check_defer_placement(self, instance):
        """
        Get instance meta data from instance
        such as "powervm:defer_placement" : "true"
        """
        def str2bool(v):
            return v.lower() in ('true', u'true')

        # The instance metatdata can be of multiple forms.
        # Handle cases : dict, list of class InstanceMetadata
        def get_defer_key_value(meta):
            if isinstance(meta, dict):
                for key in meta:
                    defer_val = meta[key]
                    if key == u'powervm:defer_placement':
                        return str2bool(defer_val)
            else:
                for entry in meta:
                    defer_key = entry.get('key', None)
                    defer_val = entry.get('value', None)
                    if defer_key == u'powervm:defer_placement':
                        return str2bool(defer_val)
            return False

        isDefer = False
        meta = instance.get('metadata', None)
        if meta:
            isDefer = get_defer_key_value(meta)

        return isDefer

    def get_pvc_flavor_by_flavor_id(self, flavor):
        """
        Get detailed info of the flavor from the PowerVC
        """
        return self._service.get_flavor_by_flavor_id(flavor)

    def update_instance_host(self, context, instance):
        """
        Update the host value of the instance from powerVC.
        """
        self._service.update_correct_host(context, instance)

    def cache_volume_data(self):
        """
        Cache the volume data during syncing the PowerVC instances.
        """
        return self._service.cache_volume_data()

    def get_local_volume_id_from_pvc_id(self, powervc_volume_id):
        list_all_volumes = self._service._cinderclient.volumes.list_all_volumes
        volume_search_opts = {"metadata": {"pvc:id": powervc_volume_id}}
        localvolumes = list_all_volumes(volume_search_opts)
        if len(localvolumes) == 0:
            return None
        if len(localvolumes) > 1:
            LOG.warning(_('More than one volume in local cinder '
                          'match one PowerVC volume: %s' %
                          (powervc_volume_id)))

        localvolume = localvolumes[0]
        return localvolume.id

    def get_pvc_root_device_name(self, pvc_id):
        if not self.cached_root_device_map.get(pvc_id):
            return self.cached_root_device_map.get(pvc_id)
        list_all_volumes = self._service._pvccinderclient.\
            volumes.list_all_volumes
        volume_search_opts = {'metadata': {'is_boot_volume': 'True'}}
        pvcvolumes = list_all_volumes(search_opts=volume_search_opts)
        for pvcvolume in pvcvolumes:
            pvcvolume_attachments = pvcvolume.attachments
            if len(pvcvolume_attachments) == 0:
                continue
            device_name = pvcvolume_attachments[0].get('device')
            self.cached_root_device_map[pvc_id] = device_name
        return self.cached_root_device_map.get(pvc_id)
