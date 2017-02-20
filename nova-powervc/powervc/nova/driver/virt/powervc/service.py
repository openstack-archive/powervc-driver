# Copyright 2013, 2014 IBM Corp.

import httplib
from novaclient import exceptions
from nova import exception
from nova.image import glance
from nova.openstack.common import loopingcall
from oslo_log import log as logging
from nova.compute import vm_states
from powervc.nova.common.exception import LiveMigrationException
from powervc.nova.driver.compute import constants
from powervc.nova.driver.compute import manager as pvc_manager
from powervc.nova.driver.virt.powervc.rpcapi import NetworkAPI
from powervc.nova.driver.virt.powervc import pvc_vm_states
from nova import db
from oslo.config import cfg
from powervc.common import constants as common_constants
from powervc.common import utils
from powervc import utils as powervc_utils
from powervc.common.gettextutils import _
from nova.exception import Invalid
from oslo.utils import excutils
from powervc.nova.driver.compute import task_states
from nova.compute import flavors
from novaclient.v1_1 import servers
from nova.objects import base as objects_base

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class InvalidSCG(Invalid):
    msg_fmt = _("Storage Connectivity Group is not supported: %(attr)s")


class PowerVCService(object):
    """A service that exposes PowerVC functionality.
    The services provided here are called by the driver.
    The services leverage the nova client to interface to the PowerVC.
    This design keeps the driver and client interface clean and simple
    and provides a workspace for any data manipulation and utility work
    that may need to be done.
    """

    def __init__(self, pvc_client):
        """Initializer."""
        self._manager = pvc_client.manager
        self._hypervisors = pvc_client.hypervisors
        self._images = pvc_client.images
        self._flavors = pvc_client.flavors
        self._client = pvc_client
        self._api = NetworkAPI()
        self._volumes = pvc_client.volumes

        # Import factory here to avoid connection to env for unittest
        from powervc.common.client import factory
        self._cinderclient = factory.\
            LOCAL.new_client(str(common_constants.SERVICE_TYPES.volume))
        self._cinderclientv2 = factory.\
            LOCAL.new_client(str(common_constants.SERVICE_TYPES.volumev2))
        self._pvccinderclient = factory.\
            POWERVC.new_client(str(common_constants.SERVICE_TYPES.volume))
        self.max_tries = CONF.powervc.volume_max_try_times

        self.longrun_loop_interval = CONF.powervc.longrun_loop_interval
        self.longrun_initial_delay = CONF.powervc.longrun_initial_delay
        # Add version checking as required

    def set_host_maintenance_mode(self, host, mode):
        resp = self._manager.set_host_maintenance_mode(host, mode)
        return resp

    def list_instances(self):
        """Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        return self._manager.list()

    def get_instance(self, instance_id):
        """Get the instance with the given id or None if not found.
        """
        return self._manager.get(instance_id)

    def list_images(self):
        """Return the information of all the images known to the virtualization
        layer, as a list.
        """
        return self._images.list()

    def list_hypervisors(self):
        """Return the information of all the hypervisors
        known to the virtualization layer, as a list.
        """
        return self._hypervisors.list()

    def get_hypervisor(self, hypervisor_id):
        """Return the information of a specific hypervisor
        known to the virtualization layer.
        """
        return self._hypervisors.get(hypervisor_id)

    def _wait_for_state_change(self, server, original_state, expected_state,
                               middle_state):
        """
        Utility method to wait for a server to change to the
        expected state.
        The process of some operation contains three states.

        param: original_state: the original state
        of the instance
        param: expected_state: the expected state
        of the instance after the operation has been
        executed
        param: middle_state: the middle state of the instance
        during the operation. If the operation has no middle state,
        it can be set as original state.
        """
        temp_server = self._manager.get(server)
        if temp_server.status == expected_state:
            LOG.debug("Service: VM %(vm_id)s successfully changed to %(state)s"
                      % {'vm_id': server.id, 'state': expected_state})
            raise loopingcall.LoopingCallDone(True)
        if (temp_server.status != original_state and
                temp_server.status != expected_state and
                temp_server.status != middle_state):
            LOG.debug(_("Expected state check failed, powerVC "
                        "instance status = %s" % temp_server.status))
            raise exception.InstanceInvalidState(
                attr=server.status,
                instance_uuid=server.id,
                state='state',
                method='_wait_for_state_change')

    def _wait_for_spawn_state_change(self, server):
        """
        Utility method to wait for a spawned server to change to the
        expected state.
        """
        temp_server = self._manager.get(server)
        temp_server_dict = temp_server.__dict__
        task_state = temp_server_dict.get('OS-EXT-STS:task_state')
        if temp_server.status == pvc_vm_states.ACTIVE:
            # Fix the issue when the instance in the status 'activating',
            # starting or stopping the instance will lead the problem.
            if task_state is not None:
                LOG.debug("VM %(vm_id)s is in the status %(state)s"
                          % {'vm_id': server.id,
                             'state': task_states.ACTIVATING})
            else:
                msg = "Service: VM %(vm_id)s successfully changed to %(state)s"
                LOG.debug(msg % {'vm_id': server.id,
                                 'state': pvc_vm_states.ACTIVE})
                raise loopingcall.LoopingCallDone(True)
        if temp_server.status == pvc_vm_states.ERROR:
            fault_message = self._get_fault_message_from_pvc_vs(temp_server)
            if fault_message is None:
                fault_message = 'Unknown error occurred.'
            raise exception.InstanceDeployFailure(
                reason=fault_message)
        if (temp_server.status != pvc_vm_states.BUILD
                and temp_server.status != pvc_vm_states.ACTIVE):
            LOG.debug(_("Expected state check failed, powerVC "
                        "instance status = %s" % temp_server.status))
            raise exception.InstanceInvalidState(
                attr=temp_server.status,
                instance_uuid=server.id,
                state='state',
                method='_wait_for_spawn_state_change')

    def _wait_for_reboot_state_change(self, server):
        """
        Utility method to wait for a rebooted server to change to the
        expected state.
        """
        temp_server = self._manager.get(server)
        task_state = getattr(temp_server, 'OS-EXT-STS:task_state')
        if not task_state:
            server_state = getattr(temp_server, 'OS-EXT-STS:vm_state')
            # Treat reboot failed if vm_state is not active after reboot
            if server_state != vm_states.ACTIVE:
                reason = "Reboot failed, current VM %(vm_id)s state: " \
                    "%(state)s." % {'vm_id': server.id,
                                    'state': server_state}
                LOG.warning(reason)
                raise exception.InstanceRebootFailure(reason=reason)
            else:
                vm_status_dict = {'vm_id': server.id,
                                  'state': pvc_vm_states.ACTIVE}
                LOG.debug("Service: VM %(vm_id)s successfully rebooted. "
                          "Current status: %(state)s" % vm_status_dict)
                raise loopingcall.LoopingCallDone(True)

    def _wait_for_resize_state_change(self, context, migration,
                                      server, instance):
        """
        Utility method to wait for a server which is resized
        to change to the expected state.

        The process of the RESIZE operation contains three states.
        SHUTOFF->RESIZE->VERIFY_RESIZE

        Because PowerVC supports the auto confirmation, the
        status of server will change to 'SHUTOFF'.

        Note:now this method only supports the 'SHUTOFF' resize mode.
        The 'Active' resize mode will be supported in the future
        release.

        """

        temp_server = self._manager.get(server)
        new_instance_type = migration['new_instance_type_id']

        # The status 'VERIFY_RESIZE' is the final status of the
        # 'RESIZE' operation
        if temp_server.status == pvc_vm_states.VERIFY_RESIZE:
            LOG.debug(
                "Service: VM %(vm_id)s successfully changed to %(state)s"
                % {'vm_id': server.id, 'state':
                   pvc_vm_states.VERIFY_RESIZE})
            raise loopingcall.LoopingCallDone(True)

        # In the auto-confirmation situation, the stauts 'SHUTOFF'
        # can be accepted
        # Check whether the resize operation task completes
        # a ) the task status of the specified instance is none
        # b ) the flavor has been updated to the new flavor

        temp_server_dict = temp_server.__dict__
        temp_server_task = temp_server_dict['OS-EXT-STS:task_state']

        if ((temp_server.status == pvc_vm_states.SHUTOFF
             or temp_server.status == pvc_vm_states.ACTIVE)
                and temp_server_task is None):
            if self._validate_flavor_update(context,
                                            new_instance_type,
                                            temp_server):
                LOG.debug(_("Service: VM %s is auto-confirmed") % server.id)
                raise loopingcall.LoopingCallDone(True)
            else:
                self._roll_back_after_resize_fail(migration, context, instance)
                LOG.info(_("Can not resize the service: VM %s for PowerVC\
                    has not enough resource.") % server.id)
                raise exception.ResizeError("Error during confirming "
                                            "the resize operation.")

        if (temp_server.status != pvc_vm_states.SHUTOFF
            and temp_server.status != pvc_vm_states.RESIZE
            and temp_server.status != pvc_vm_states.ACTIVE
                and temp_server.status != pvc_vm_states.VERIFY_RESIZE):
            LOG.debug(_("Service: VM %s is the wrong status.") % server.id)
            error_message = self._get_resize_fault_message(temp_server_dict)
            if error_message is not None:
                LOG.warning("Get error during resizing the instance"
                            " in the PowerVC:")
                self._roll_back_after_resize_fail(migration, context, instance)
                raise exception.\
                    ResizeError("Get error: %s during"
                                "resizing the instance in the PowerVC:"
                                % error_message)
            self._roll_back_after_resize_fail(migration, context, instance)
            raise exception.\
                InstanceInvalidState(attr=temp_server.status,
                                     instance_uuid=server.id,
                                     state='state',
                                     method='_wait_for_resize_state_change')

    def _get_resize_fault_message(self, server):
        """
        Utility to get the error message of the resize operation.
        :param server: the PowerVC server instance.
        """
        detail_server = server
        fault_message = None
        if detail_server is not None:
            fault = detail_server.get('fault')
            if fault is not None:
                fault_message = fault.get('message')
        else:
            LOG.warning("Fail to find the instance with the id: %s", server.id)

        return fault_message

    def _roll_back_after_resize_fail(self, migration, context, instance):
        """
        Utility to roll back the instance after the resize instance fails.
        :param migration
        :param context
        :param instance
        """
        old_instance_type_id = migration['old_instance_type_id']
        new_instance_type_id = migration['new_instance_type_id']
        if old_instance_type_id != new_instance_type_id:
            try:
                pvc_flavor = flavors.get_flavor(old_instance_type_id)
            except Exception:
                LOG.info(_("Getting exception during getting the flavor."))
                LOG.info(_("Rolling back of the flavor fails."))
                return
            sys_meta = dict()
            sys_meta = flavors.save_flavor_info(sys_meta, pvc_flavor)
            instance.instance_type_id = pvc_flavor['id']
            instance.memory_mb = pvc_flavor['memory_mb']
            instance.vcpus = pvc_flavor['vcpus']
            instance.root_gb = pvc_flavor['root_gb']
            instance.ephemeral_gb = pvc_flavor['ephemeral_gb']
            instance.system_metadata = sys_meta
            instance.save()

    def _wait_for_confirm_state_change(self, server):
        """
        This method is used to wait and check the state of
        the confirmation change.

        :param context: the context of the hosting OS.
        :param new_instance_type: the new instance type.
        :param server: the VM server instance
        """

        temp_server = self._manager.get(server)

        """
         The PowerVC driver supports the auto-confirm.
         In the 'SHUTOFF' mode resize, when confirm the resize,
         the server is not started. So the accepted status of server
         is 'SHUTOFF'.

        """

        temp_server_dict = temp_server.__dict__
        temp_server_task = temp_server_dict['OS-EXT-STS:task_state']

        if (temp_server.status == pvc_vm_states.SHUTOFF and
                temp_server_task is None):
                LOG.debug(_("The resize operation of the service:\
                            VM %s is confirmed") % server.id)
                raise loopingcall.LoopingCallDone(True)

        if (temp_server.status == pvc_vm_states.ACTIVE and
                temp_server_task is None):
                LOG.debug(_("The resize operation of the service:\
                            VM %s is confirmed") % server.id)
                raise loopingcall.LoopingCallDone(True)

        if (temp_server.status != pvc_vm_states.SHUTOFF and
            temp_server.status != pvc_vm_states.ACTIVE and
                temp_server.status != pvc_vm_states.VERIFY_RESIZE):
            raise exception.\
                InstanceInvalidState(attr=temp_server.status,
                                     instance_uuid=server.id,
                                     state='state',
                                     method='_wait_for_confirm_state_change')

    def _validate_flavor_update(self, context, new_instance_type, server):
        """
        This method is used to validate whether the flavor is updated
        after the resize.

        :param context: the context of the hosting OS.
        :param new_instance_type: the new instance type.
        :param server: the VM server instance
        :return Ture if the flavor is updated, otherwise False.
        """

        is_flavor_updated = False

        flavor = db.flavor_get(context, new_instance_type)
        memory_mb = flavor['memory_mb']
        vcpus = flavor['vcpus']
        root_gb = flavor['root_gb']
        ephemeral_gb = flavor['ephemeral_gb']

        pvc_flavor = server.flavor
        pvc_flavor_id = pvc_flavor['id']

        try:
            pvc_flavor = self.get_flavor_by_flavor_id(pvc_flavor_id)
        except Exception:
            LOG.info(_("Ignore the exception during getting the flavor"))
            return is_flavor_updated

        pvc_flavor_dict = pvc_flavor.__dict__

        if (memory_mb == pvc_flavor_dict['ram']
            and vcpus == pvc_flavor_dict['vcpus']
            and root_gb == pvc_flavor_dict['disk']
            and ephemeral_gb == pvc_flavor_dict.
                get('OS-FLV-EXT-DATA:ephemeral', 0)):
            LOG.info(_("The flavor of the server %s has been updated\
                      successfully.") % server.id)
            is_flavor_updated = True

        return is_flavor_updated

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

    def list_os_attachments(self, server_id):
        """List volumes of the specified instance"""
        return self._volumes.get_server_volumes(server_id)

    def detach_volume(self, connection_info, instance, mountpoint):
        """Detach the specified volume from the specified instance"""
        server_id = instance['metadata']['pvc_id']
        if 'serial' in connection_info:
            local_volume_id = connection_info['serial']
            volume_id = self._get_pvc_volume_id(local_volume_id)
        else:
            LOG.warning(_("VolumeId missing in detaching volume"))
        self._volumes.delete_server_volume(server_id, volume_id)

    def power_off(self, instance):
        """Power off the specified instance."""
        server_instance = self._get_server(instance)
        server = self._get_pvcserver(server_instance)
        # Exit Immediately if the server is already stopped
        # This is only the case when the OS and PVC states are
        # not in sync.
        # Note: Should verify these states....
        if (server.status == pvc_vm_states.SHUTOFF):
            LOG.debug("Service: Instance state out of sync, current state: %s"
                      % server.status)
            return
        # When the task status of the instance in the PowerVC is 'ACTIVATING',
        # Try to stop this instance will fail.
        server_dict = server.__dict__
        task_state = server_dict.get('OS-EXT-STS:task_state')
        if (task_state == task_states.ACTIVATING):
            LOG.debug("The task status of the instance: %s"
                      % task_state)
            reason = _("The instance in the task status: %s can not"
                       " be stopped."
                       % task_state)
            raise exception.InstanceUnacceptable(instance_id=server.id,
                                                 reason=reason)

        response = self._manager.stop(server)
        self._validate_response(response)

        timer = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_state_change, server,
            server.status, pvc_vm_states.SHUTOFF, pvc_vm_states.SHUTOFF)

        return timer.start(self.longrun_loop_interval,
                           self.longrun_initial_delay).wait()

    def power_on(self, instance):
        """Power on the specified instance."""
        server_instance = self._get_server(instance)
        server = self._get_pvcserver(server_instance)

        # Exit Immediately if the server is already started
        # This is only the case when the OS and PVC states are
        # not in sync.
        if server.status == pvc_vm_states.ACTIVE:
            LOG.debug("Service: Instance state out of sync, current state: %s"
                      % server.status)
            return

        # When the task status of the instance in the PowerVC is 'ACTIVATING',
        # Try to start this instance will fail.
        server_dict = server.__dict__
        task_state = server_dict.get('OS-EXT-STS:task_state')
        if (task_state == task_states.ACTIVATING):
            LOG.debug("The task status of the instance: %s."
                      % task_state)
            reason = _("The instance in the task status: %s can not be started"
                       % task_state)
            raise exception.InstanceUnacceptable(instance_id=server.id,
                                                 reason=reason)

        response = self._manager.start(server)
        self._validate_response(response)

        timer = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_state_change, server,
            server.status, pvc_vm_states.ACTIVE, pvc_vm_states.ACTIVE)

        return timer.start(self.longrun_loop_interval,
                           self.longrun_initial_delay).wait()

    def _get_pvcserver(self, server_instance):
        """
        This method handles the call to PowerVC to
        get the server
        """
        return self._manager.get(server_instance)

    def _get_server(self, instance):
        """
        This method handles converting a a hosting instance
        into an powerVC instance for nova client use.
        """
        instance_primitive = objects_base.obj_to_primitive(instance)
        server = servers.Server(self._manager, instance_primitive)

        # Check whether we can get the metadata from instance
        key = 'metadata'
        pvc_id = 0
        if key not in instance:
            LOG.info(_('Could not find the metadata from the instance.'))
            server.id = pvc_id
            return server
        metadatas = instance[key]

        # Check whether we can get the pvc_id from the metadata
        key = 'pvc_id'

        # Handle the situation when doing resize operation,
        # the metadata in the instance is list type.
        if (metadatas is not None and isinstance(metadatas, list)):
            for metadata in metadatas:
                if metadata['key'] == key:
                    pvc_id = metadata['value']
                    server.id = pvc_id
                    return server
            # If no pvc_id in list, return it by _get_pvcid_from_metadata()
            server.id = self._get_pvcid_from_metadata(instance)
            return server

        if metadatas == [] or key not in metadatas.keys():
            LOG.info(_('Could not find the pvc_id from the metadata.'))
            server.id = pvc_id
            return server

        # Get the pvc_id of the instance
        pvc_id = metadatas[key]
        server.id = pvc_id
        return server

    def _get_pvcid_from_metadata(self, instance):
        """
            Because the data structure of the instance passed by
            the nova manager is different from normal structure,
            use this method to get the PowerVC id from the instance
            metadata
        """
        pvc_id = ''
        metadatas = instance['metadata']
        for key in metadatas:
            if key == "pvc_id":
                pvc_id = metadatas[key]
                break
        return pvc_id

    def list_flavors(self):
        """
        Return the names of all the flavors known to the virtualization
        layer, as a list.
        """
        return self._flavors.list()

    def get_flavor_by_flavor_id(self, flavor):
        """
        Return the specified flavor with the flavor id
        """
        return self._flavors.get(flavor)

    def get_flavor_extraspecs(self, flavor):
        """
        Return the extraspecs defined for a flavor as a dict.
        """
        return flavor.get_keys()

    def _update_local_instance_by_pvc_created_instance(self,
                                                       context,
                                                       orig_instance,
                                                       created_server):
        """
            update the original instance with the created instance
        """
        created_instance = created_server.__dict__
        # get original metadata from DB and insert the pvc_id
        meta = orig_instance.get('metadata')
        # update powervc specified metadata to hosting os vm instance
        powervc_meta = created_instance.get('metadata')
        if powervc_meta:
            meta.update(powervc_meta)
        # Always override pvc_id with created_server id regardless even if
        # PowerVC instance has such pvc_id in metadata
        meta.update(pvc_id=created_instance['id'])
        node = created_instance.get('OS-EXT-SRV-ATTR:hypervisor_hostname',
                                    None)
        host = created_instance.get('OS-EXT-SRV-ATTR:host', None)
        powerstate = created_instance['OS-EXT-STS:power_state']
        orig_instance['node'] = node
        orig_instance['host'] = host
        orig_instance['architecture'] = constants.PPC64
        orig_instance['power_state'] = powerstate
        orig_instance['metadata'] = meta
        # remove activation engine configuration data as db is not allowed
        orig_instance.system_metadata.pop('configuration_data', None)
        orig_instance.save()
        LOG.debug('Saved instance after created PowerVC instance: %s',
                  orig_instance)

    def spawn(self, context, instance, injected_files, name, imageUUID,
              flavorDict, nics, hypervisorID, availability_zone, isDefer,
              scheduler_hints):
        """Call pvcnovaclient to boot a VM on powerVC
        :param context: admin context
        :param instance: passed-in instance
        :param injected_files: User files to inject into instance.
        :param name: server name
        :param imageUUID: Image UUID on powerVC
        :param flavorDict: a dictionary which contains flavor info
        :param networkUUID: Network config UUID on powerVC
        :param hypervisorID: Hypervisor ID (a number) on powerVC
        :param availability_zone: the availability_zone of host
        :param isDefer: defer_placement flag
        """
        createdServer = None

        # extract activation data from instance
        meta = instance._metadata
        key_name = instance.key_name

        extra_specs_key = constants.EXTRA_SPECS
        scg_key = constants.SCG_KEY
        storage_template_key = constants.STORAGE_TEMPLATE_KEY

        if 'selected-scg' in meta.keys():
            LOG.info(_('Boot with scg specified: %s'
                       '.') % (meta['selected-scg']))
            flavorDict[extra_specs_key][scg_key] = meta['selected-scg']

        if 'selected-storage-template' in meta.keys():
            LOG.info(_('Boot with storage template specified: %s'
                       '.') % (meta['selected-storage-template']))
            flavorDict[extra_specs_key][storage_template_key] = \
                meta['selected-storage-template']

        self.validate_update_scg(flavorDict)

        # key_data = instance.key_data
        config_drive = instance._config_drive
        userdata = instance.user_data   # already base64 encoded by local OS

        if not isDefer:
            LOG.debug(_('Enter to invoke powervc api to deploy instance'
                        'of %s, isDefer status is %s') % (name, isDefer))
            createdServer = \
                self._manager.create(name=name,
                                     image=imageUUID,
                                     flavor=flavorDict,
                                     meta=meta,
                                     files=injected_files,
                                     userdata=userdata,
                                     key_name=key_name,
                                     # OpenStack API doesn't support key_data,
                                     # key_data = key_data,
                                     config_drive=config_drive,
                                     nics=nics,
                                     hypervisor=hypervisorID,
                                     availability_zone=availability_zone,
                                     scheduler_hints=scheduler_hints)
            LOG.debug(_('Exit to invoke powervc api to deploy instance of %s,'
                        'isDefer status is %s') % (name, isDefer))
        else:
            LOG.debug(_('Enter to invoke powervc api to deploy instance of %s,'
                        'isDefer status is %s') % (name, isDefer))
            createdServer = self._manager.create(name=name,
                                                 image=imageUUID,
                                                 flavor=flavorDict,
                                                 meta=meta,
                                                 files=injected_files,
                                                 userdata=userdata,
                                                 key_name=key_name,
                                                 # OpenStack API doesn't
                                                 # support key_data,
                                                 # key_data = key_data,
                                                 config_drive=config_drive,
                                                 nics=nics,
                                                 scheduler_hints=scheduler_hints)
            LOG.debug(_('Exit to invoke powervc api to deploy instance of %s,'
                        'isDefer status is %s') % (name, isDefer))

        LOG.debug(_('Created Server: %s' % createdServer))
        LOG.debug(_(
            'Server status is %s after creating' % createdServer.status))
        # update local DB instance with powervc created one
        self._update_local_instance_by_pvc_created_instance(
            context, instance, createdServer)

        # If the vm is building, wait until vm status is ACTIVE or ERROR
        if createdServer.status == pvc_vm_states.BUILD:
            LOG.debug(_('wait until created vm status is ACTIVE or ERROR'))
            timer = loopingcall.FixedIntervalLoopingCall(
                self._wait_for_spawn_state_change, createdServer)

            try:
                timer.start(self.longrun_loop_interval * 2,
                            self.longrun_initial_delay * 2).wait()
                LOG.debug(_('Create VM succeeded'))
            except exception.InstanceInvalidState as e:
                with excutils.save_and_reraise_exception():
                    # set powervc fault message to exception and throw e
                    e.message = self._get_fault_message(createdServer)

            # verify the server's status after wait
            createdServer = self._manager.get(createdServer)
            LOG.debug(_(
                'Server status is %s after waiting' % createdServer.status))

        elif createdServer.status != pvc_vm_states.ACTIVE:
            exp = exception.InstanceInvalidState()
            exp.message = self._get_fault_message(createdServer)
            raise exp

        # Again, update local DB instance with powervc created one
        # in case some fields changed after boot.
        # Copy the powervc specified properties into metadata
        createdServer.metadata = \
            powervc_utils.fill_metadata_dict_by_pvc_instance(
                createdServer.metadata,
                createdServer.__dict__)
        self._update_local_instance_by_pvc_created_instance(
            context, instance, createdServer)
        return createdServer

    def _get_fault_message(self, createdServer):
        """try to get error message from powerVC when boot vm failed
        """
        errorServer = self._manager.get(createdServer)
        return self._get_fault_message_from_pvc_vs(errorServer)

    def _get_fault_message_from_pvc_vs(self, errorServer):
        """try to get error message from powerVC when boot vm failed
        """
        fault_message = None
        fault_msg = getattr(errorServer, 'fault', None)
        if fault_msg:
            # set powervc fault message to exception and throw e
            fault_message = fault_msg.get('message', None)
        LOG.warning(_('Failed to create VM, reason: %s' % fault_message))
        return fault_message

    def validate_update_scg(self, flavorDict):
        """
        Validate the flavor dict for scg
        -if extra specs key is available and if scg is specified in extra
        specs dict, then verify if scg is same as supported by our driver.
        If it is not the supported scg, fail the operation
        -if extra specs key is not available, or scg is not specified in extra
        specs dict, then add the scg information to the extra specs dict and
        update the flavor dict.
        """
        scg_name_list = CONF.powervc.storage_connectivity_group
        scg_id_list = [utils.get_utils().get_scg_id_by_scgName(scg_name)
                       for scg_name in scg_name_list]
        LOG.info(_('The first scg-uuid is: %s.') % scg_id_list[0])
        scg_key = constants.SCG_KEY
        extra_specs_key = constants.EXTRA_SPECS

        if extra_specs_key in flavorDict:
            extra_specs = flavorDict[extra_specs_key]
            if scg_key in extra_specs:
                if extra_specs[scg_key] in scg_id_list:
                    return
                else:
                    LOG.info(_("Function failed due to unsupported"
                               " storage connectivity group."))
                    raise InvalidSCG(attr=extra_specs[scg_key])

        LOG.info(_('Boot vm with no scg specified, leave extra_specs empty'))
        return

    def destroy(self, instance):
        """
            Destroy the VM instance in the PowerVC host.
        """
        server_instance = self._get_server(instance)

        # If we can not find the VM instance in the PowerVC host,
        # the destroy operation should be successful.
        try:
            server = self._manager.get(server_instance)
        except exceptions.NotFound:
            LOG.debug("Service: Can not find VM %s in the PowerVC."
                      % server_instance.id)
            return True

        LOG.debug(_("Enter to invoke powervc api to delete instance of %s")
                  % server)
        delete_response = self._manager.delete(server)
        LOG.debug(_("Exit to invoke powervc api to delete instance of %s")
                  % server)

        self._validate_response(delete_response)

        def _wait_for_destroy():
            """
                The method is used to call at an interval until the VM
                is gone.
            """
            try:
                get_server_response = self._manager.get(server)
            except exceptions.NotFound:
                LOG.info(
                    _("VM instance %s was successfully deleted.")
                    % server.id)
                raise loopingcall.LoopingCallDone(True)

            server_response = get_server_response.__dict__

            # There is a window where the instance will go out of deleting
            # task state and report a status of DELETED and a task state of
            # None. Recognize this as a sucessful delete completion as well.
            if (server_response['OS-EXT-STS:task_state'] is None and
                    server_response['status'] == 'DELETED'):
                LOG.info(
                    _("VM instance %s was successfully deleted.")
                    % server.id)
                raise loopingcall.LoopingCallDone(True)

            if (server_response['OS-EXT-STS:task_state'] != 'deleting' and
                    server_response['status'] != 'DELETED'):
                LOG.info(_("VM %s failed to delete, instance details: %s ") %
                         (server.id, server_response))
                raise exception.InstanceTerminationFailure(server)

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_destroy)
        timer_result = timer.start(self.longrun_loop_interval * 2,
                                   self.longrun_initial_delay * 2).wait()
        # Add the pvc instance to the global deleted list
        pvc_manager.deleted_pvc_ids.add(server.id)
        LOG.debug('Added the deleted powervc instance id %s to the global '
                  'deletion list', server.id)
        return timer_result

    def set_device_id_on_port_by_pvc_instance_uuid(self,
                                                   ctx,
                                                   local_ins_id,
                                                   pvc_ins_id):
        """
            Query a sync. local port by a pvc instance id,
            then set its device_id to a local instance id.
        """
        local_ports = self._api.\
            set_device_id_on_port_by_pvc_instance_uuid(ctx,
                                                       local_ins_id,
                                                       pvc_ins_id)
        return local_ports

    def get_pvc_network_uuid(self, ctx, local_id):
        """
            Given a local netowrk id, return a powerVC network id.
        """
        pvc_id = self._api.get_pvc_network_uuid(ctx, local_id)
        return pvc_id

    def get_pvc_port_uuid(self, ctx, local_id):
        """
            Given a local port id, return a powerVC port id.
        """
        pvc_id = self._api.get_pvc_port_uuid(ctx, local_id)
        return pvc_id

    def _get_instance_resize_properties(self, context, new_instance_type,
                                        server):
        """
        Get the dynamic instance customization properties.
        The dynamic properties are those that can be modified on an
        existing instance.

        :param instance: the instance which needs to be resized
        :returns: dictionary of dynamic properties
        :new_instance_type: the flavor type
        """
        flavor = db.flavor_get(context, new_instance_type)
        flavor_extras = self.\
            _get_flavor_extra_specs(context, flavor)
        flavor_extras_target = dict()
        if server.status == pvc_vm_states.ACTIVE:
            flavor_extras_source = flavor_extras
            for key in flavor_extras_source.keys():
                if (key.find('min') == -1 and
                        key.find('max') == -1):
                    flavor_extras_target[key] = flavor_extras_source[key]
        else:
            flavor_extras_target = flavor_extras

        flavor_props = {'vcpus': flavor['vcpus'],
                        'ram': flavor['memory_mb'],
                        'disk': getattr(server, 'root_gb', flavor['root_gb']),
                        'extra_specs': flavor_extras_target
                        }

        self.validate_update_scg(flavor_props)
        props = {'flavor': flavor_props}
        return props

    def _get_flavor_extra_specs(self, context, flavor):
        """
        The method _get_flavor_extra_specs is used to get the PowerVC flavor
        extra_specs data
        """
        flavor_id = flavor['flavorid']
        value = db.flavor_extra_specs_get(context, flavor_id)
        return value

    def _resize(self, server, props):
        """
        Resize a server's resources.
        :para server; the :class:`Server` to share onto.
        :para body: the body of rest request

        """
        LOG.debug(_("Enter to invoke powervc api to resize instance of %s")
                  % server.id)
        response = self._manager._resize_pvc(server, props)
        LOG.debug(_("Exit to invoke powervc api to resize instance of %s")
                  % server.id)
        return response

    def resize_instance(self, context, migration, instance,
                        image_meta):
        """
            Resize the specified VM instance on the PowerVC host.
        """
        # The resize operation REST API of PowerVC is different
        # from the standard OpenStack.

        server_instance = servers.Server(self._manager, instance)
        server_instance.id = self._get_pvcid_from_metadata(instance)
        server = self._manager.get(server_instance)

        LOG.debug("Starting to resize the instance %s",
                  server.id)
        new_instance_type = migration['new_instance_type_id']
        props = self._get_instance_resize_properties(context,
                                                     new_instance_type,
                                                     server)
        response = self._resize(server, props)
        self._validate_response(response)

        timer = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_resize_state_change, context,
            migration, server, instance)

        return timer.start(self.longrun_loop_interval * 3,
                           self.longrun_initial_delay * 2).wait()

    def confirm_migration(self, instance):
        """
            Confirm a resize operation.
        """
        server_instance = self._get_server(instance)
        server = self._manager.get(server_instance)

        server_dict = server.__dict__
        server_task = server_dict['OS-EXT-STS:task_state']

        if server.status == pvc_vm_states.ERROR:
            raise exception.ResizeError("Error during confirming "
                                        "the resize operation.")

        # Handle with the auto-confirmation situation
        if (server.status == pvc_vm_states.ACTIVE and
                server_task is None):
            LOG.info(_("The VM instance %s is auto-confirmed successfully.")
                     % server.id)
            return True

        if (server.status == pvc_vm_states.SHUTOFF and
                server_task is None):
            LOG.info(_("The VM instance %s is auto-confirmed successfully.")
                     % server.id)
            return True

        try:
            response = self._manager.confirm_resize(server)
            self._validate_response(response)
        except Exception as exc:
            LOG.info(_("Getting the exception during confirming the resize of "
                       "the instance %s.") % server.id)
            LOG.info(_("The exception: %s") % exc)
            server = self._manager.get(server_instance)
            if server.status == pvc_vm_states.ERROR:
                raise exception.ResizeError("Error during confirming "
                                            "the resize operation.")
            timer = loopingcall.FixedIntervalLoopingCall(
                self._wait_for_confirm_state_change, server)
            return timer.start(self.longrun_loop_interval * 2,
                               self.longrun_initial_delay).wait()

        timer = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_confirm_state_change, server)

        return timer.start(self.longrun_loop_interval * 2,
                           self.longrun_initial_delay).wait()

    def attach_volume(self, connection_info, instance, mountpoint):
        """
            Attach the specified volume to the specified instance
        """
        server_instance = self._get_server(instance)
        server = self._manager.get(server_instance)

        server_id = server.id
        local_volume_id = connection_info['serial']
        volume_id = self._get_pvc_volume_id(local_volume_id)

        if volume_id == '':
            LOG.debug("Could not get the PowerVC volume id "
                      "with local volume id.")
            raise exception.VolumeUnattached

        self._volumes.create_server_volume(server_id,
                                           volume_id,
                                           mountpoint)

    def list_attachments_of_instance(self, server_id):
        """
            Lists the volume attachments for the specified server.
        """

        response = self._volumes.get_server_volumes(server_id)

        return response

    def _get_pvc_volume_id(self, local_id):
        """
        The method get_pvc_volume_id is used to get the PowerVC volume id
        with the local volume id
        """
        pvc_volume_id = ''

        local_volume = self._cinderclientv2.volumes.get(local_id)

        if local_volume is None:
            return pvc_volume_id

        metadata = getattr(local_volume, 'metadata', '')
        if metadata == '':
            return pvc_volume_id

        if "pvc:id" in metadata.keys():
            pvc_volume_id = metadata["pvc:id"]

        return pvc_volume_id

    def snapshot(self, context, instance,
                 local_image_id, image):
        """
        Captures a workload into an image.
        :param context: the context for the capture
        :param instance:  the instance to be capture
        :param local_image_id: the id of the local image created for the
        snapshot
        :param image: image object to update
        """
        server_instance = self._get_server(instance)
        server = self._get_pvcserver(server_instance)
        image_name = image["name"]
        glance_image_service = glance.get_default_image_service()

        # nova is going to pick up the uuid from the image the instance was
        # deployed from.  We need to remove it to prevent treating this image
        # as if it is the base deploy image
        image_props = image["properties"]
        if common_constants.POWERVC_UUID_KEY in image_props:
            props = {'properties': {common_constants.POWERVC_UUID_KEY: None}}
            glance_image_service.update(context, local_image_id, props,
                                        purge_props=False)

        glance_powervc_uuid_value = \
            server.create_image(image_name, {common_constants.LOCAL_UUID_KEY:
                                             image["id"]})

        image_data = {
            'properties': {
                common_constants.POWERVC_UUID_KEY: glance_powervc_uuid_value
            }
        }

        glance_image_service.update(context, local_image_id, image_data,
                                    purge_props=False)

        def _wait_for_snapshot():
            """
                The method is used to call at an interval until the
                capture is complete
            """
            get_server_response = self._manager.get(server)
            server_response = get_server_response.__dict__
            task_state = server_response['OS-EXT-STS:task_state']

            if task_state is None or task_state == 'None':
                LOG.info(_("Capture of VM instance %s is complete.") %
                         server.id)
                raise loopingcall.LoopingCallDone(True)
            LOG.debug(_("Capture of VM instance %s in state %s.") %
                      (server.id, task_state))

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_snapshot)
        return timer.start(self.longrun_loop_interval,
                           self.longrun_initial_delay).wait()

    def live_migrate(self, instance, dest, migrate_data):
        """
        Live migrate a PowerVC instance.
        :param instance: Local OS instance
        :param dest: Destination host
        :param migrate_data: implementation specific data dict
        """
        server_instance = self._get_server(instance)
        server = self._manager.get(server_instance)

        resp = self._manager.live_migrate(server, dest, False, False)
        self._validate_response(resp)

        server_dict = server.__dict__
        orig_host = server_dict['OS-EXT-SRV-ATTR:host']

        def _wait_for_live_migration():
            """
                The method is used to call at an interval until the
                instance transitions from Migrating state .
            """
            pvc_server = self._manager.get(server)
            pvc_server_dict = pvc_server.__dict__
            current_host = pvc_server_dict['OS-EXT-SRV-ATTR:host']
            pvc_task_state = pvc_server_dict.get('OS-EXT-STS:task_state')
            LOG.debug(_('Original Host %s, Current Host %s, powervc instance '
                        'state is %s, task_state is %s') %
                      (orig_host, current_host, pvc_server.status,
                       pvc_task_state))
            if (pvc_server.status != pvc_vm_states.MIGRATING and
                    current_host != orig_host):
                LOG.info(_("Instance %s completed migration.") % pvc_server.id)
                raise loopingcall.LoopingCallDone(True)
            if pvc_task_state is None and current_host == orig_host and\
                pvc_server.status in (pvc_vm_states.ACTIVE,
                                      pvc_vm_states.ERROR):
                LOG.error('Instance %s failed to migrate to another host, '
                          'please check with PowerVC console error message or '
                          'log file', pvc_server.id)
                raise LiveMigrationException(pvc_server.id)

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_live_migration)
        return timer.start(self.longrun_loop_interval * 3,
                           self.longrun_initial_delay * 2).wait()

    def reboot(self, instance, reboot_type):
        """Reboot the specified instance.

        After this is called successfully, the instance's state
        goes back to power_state.RUNNING. The virtualization
        platform should ensure that the reboot action has completed
        successfully even in cases in which the underlying domain/vm
        is paused or halted/stopped.

        :param instance: nova.objects.instance.Instance
        :param reboot_type: Either a HARD or SOFT reboot
        """
        server_instance = self._get_server(instance)
        server = self._manager.get(server_instance)

        if reboot_type == "SOFT":
            server.reboot(servers.REBOOT_SOFT)
        else:
            server.reboot(servers.REBOOT_HARD)

        # loop when vm state status is not none
        LOG.debug(_('wait until rebooted server task state is none'))
        timer = loopingcall.FixedIntervalLoopingCall(
            self._wait_for_reboot_state_change, server)
        try:
            timer.start(self.longrun_loop_interval * 2,
                        self.longrun_initial_delay).wait()
            LOG.debug(_('Reboot VM succeeded'))
        except exception.InstanceRebootFailure:
            with excutils.save_and_reraise_exception():
                LOG.warning("Reboot VM failed.")

    def update_correct_host(self, context, instance):
        """
        Update the property host of the instance.
        When the VM instance is resized, the Nova will select the
        host to migrate it. In order to handle with this situation,
        we need to update the property host of the instance after the
        resize operation. Additionally, when live migration is deferred
        to powervc, we will not know the host as well.  This method
        needs to update the host, node and hostname values as they
        are all related to an instance belonging to a new compute
        node.
        """
        server_instance = self._get_server(instance)
        server = self._manager.get(server_instance)
        server_dict = server.__dict__
        host = \
            powervc_utils.normalize_host(server_dict['OS-EXT-SRV-ATTR:host'])
        hostname = server_dict['OS-EXT-SRV-ATTR:hypervisor_hostname']
        try:
            db.instance_update(context, instance['uuid'],
                               {'host': host,
                                'node': hostname,
                                'hostname': hostname})
        except Exception as exc:
            LOG.info(_("Fail to set the host of VM instance %s.")
                     % server.id)
            raise exc

    def get_valid_destinations(self, instance_ref):
        """
        Utility method to get valid hosts for an instance to
        move to.
        """
        server_instance = self._get_server(instance_ref)
        server = self._manager.get(server_instance)
        return self._manager.list_instance_storage_viable_hosts(server)

    def _is_live_migration_valid(self, status, health_status):
        """
        Utility method to determine if we can safely request a live migration
        on the powervc system. Ideally, powerVC should be giving its clients
        a safer API, but for this release we need to do our best to make sure
        its safe to call.  This method does 2 things, checks that the instance
        status is active and secondly that there is a valid RMC connection to
        HMC with the instance. If there is not a valid connection the instance
        will go to error state in powervc, although the instance can safely be
        recovered, we should not send the request altogether.
        :param status: (str) instance status from powervc
        :param health_status: (tuple, examples below) of health information.

        Examples of OK instance:
        { u'health_value': u'OK',
          u'id': u'ba93a763-061e-49a1-807d-aa053bccdc81'
        }

        { u'health_value': u'UNKNOWN',
          u'unknown_reason': u'Unable to get related hypervisor data'
        }

        Example of WARNING instance:
        { u'health_value': u'WARNING',
          u'id': u'a370885f-4bff-4d8e-869f-2aa64545a7aa',
          u'value_reason': [
             {u'resource_local': u'server',
              u'resource_id': u'a370885f-4bff-4d8e-869f-2aa64545a7aa',
              u'display_name': u'aix',
              u'resource_property_key': u'rmc_state',
              u'resource_property_value': u'inactive'},
             {u'resource_local': u'server',
              u'resource_id': u'a370885f-4bff-4d8e-869f-2aa64545a7aa',
              u'display_name': u'aix',
              u'resource_property_key': u'vm_state',
              u'resource_property_value': u'stopped'}
              ]
        }
        """
        if (status != 'ACTIVE'):
            return False
        if (health_status is not None and
            (health_status['health_value'] == 'OK' or
             health_status['health_value'] == 'UNKNOWN')):
                return True
        else:
            if (health_status is not None and
                    'value_reason' in health_status):
                for reason in health_status['value_reason']:
                    if (reason is not None and
                        'resource_property_key' in reason and
                        'resource_property_value' in reason and
                        reason['resource_property_key'] == 'rmc_state' and
                            reason['resource_property_value'] == 'inactive'):
                                return False
        return True

    def cache_volume_data(self):
        """
        Cache the volume data during the sync instances.
        """
        cache_volume = {}
        local_volumes = self._cinderclient.volumes.list_all_volumes(
            search_opts={'all_tenants': 1})

        for local_volume in local_volumes:
            metadata = getattr(local_volume, 'metadata', '')
            if metadata == '':
                continue
            if 'pvc:id' in metadata.keys():
                pvc_volume_id = metadata['pvc:id']
                local_volume_id = getattr(local_volume, 'id', '')
                if pvc_volume_id is not None and local_volume_id != '':
                    cache_volume[pvc_volume_id] = local_volume_id
        return cache_volume

    def attach_interface(self, context, instance, local_port_id,
                         local_network_id, ipAddress):
        """attach a new port to a specified vm
        :param context: context for this action
        :param instance: the vm instance that new interface attach to
        :param local_port_id: the local port uuid
        :param local_network_id: the powervc network uuid
        :param ipAddress: the ipv4 address that set to the vm
        """
        pvc_port_id = self.get_pvc_port_uuid(context, local_port_id)
        # get client server instance from a db instance
        server_with_pvc_id = self._get_server(instance)
        # get the powervc client server instance from novaclient
        server_client_obj = self._manager.get(server_with_pvc_id)
        # PowerVC restAPI will thrown BadRequest exception if set port_id
        # and net-id/ipaddress in the same time.
        # So if there is powervc port id matches to local port id existed, set
        # the net_id and ipaddress to ''.
        # If there is no port in powervc matches to local port existed, get
        # and call restAPI with net-id and ipAddress.
        if pvc_port_id:
            pvc_network_id = ''
            ipAddress = ''
        else:
            # the 'net-id' will be changed to the 'uuid' in the boot method
            pvc_network_id = self.get_pvc_network_uuid(context,
                                                       local_network_id)
            LOG.debug(_("PowerVC nic uuid: %s") % pvc_network_id)
        # get the raw_response data from patched novaclient interface attach
        # function. For detail, see the extensions/nova.py#interface_attach()
        server_client_obj.interface_attach(pvc_port_id, pvc_network_id,
                                           ipAddress)
        # Call Neutron RPC to update the pvc id to port obj immediately.
        # self.set_pvc_id_to_port(context, local_port_id, pvc_port_id)

        # TODO Loop to get the pvc_id from local db. Return this method until
        # pvc_id got verified in local db, Default timeout is 150s

    def detach_interface(self, context, instance, vif):
        """detach a port from a specified vm
        :param context: context for this action
        :param instance: the vm instance that new interface attach to
        :param vif: the local interface info
        """
        # get client server instance from a db instance
        server_with_pvc_id = self._get_server(instance)
        server_client_obj = self._manager.get(server_with_pvc_id)

        pvc_port_uuid = None
        local_port_id = vif.get('id')
        if local_port_id:
            pvc_port_uuid = self._api.get_pvc_port_uuid(context,
                                                        local_port_id)

        if not pvc_port_uuid:
            LOG.warning(_('Cannot retrieve pvc port id for local port %s.'
                          ' Attempt to filter out pvc port id with IP'
                          ' addresses attached to pvc instance %s'),
                        local_port_id, server_with_pvc_id.id)
            # Failed to retrieve powervc port uuid through local port id
            # This can be caused by local port deleted has already been handled
            # Try to locate pvc port id by IP address

            local_ips = vif.fixed_ips()
            if not local_ips:
                LOG.warning(_('Cannot locate detach port id for pvc server %s'
                              ', because no local ips found on local VIF %s'),
                            server_with_pvc_id.id, vif)
                return

            candidate_ips = []
            for local_ip in local_ips:
                ip_addr = local_ip.get('address')
                if ip_addr:
                    candidate_ips.append(ip_addr)
            if not candidate_ips:
                LOG.warning(_('Cannot locate detach port id for pvc server %s'
                              ', because no ip address found on local VIF %s'),
                            server_with_pvc_id.id, vif)
                return

            pvc_interface_list = server_client_obj.interface_list()
            for pvc_intf in pvc_interface_list:
                pvc_fixed_ips = pvc_intf._info.get('fixed_ips')
                if not pvc_fixed_ips:
                    continue
                pvc_ips = []
                for pvc_ip in pvc_fixed_ips:
                    pvc_ips.append(pvc_ip.get('ip_address'))
                cmp_ips = [x for x in pvc_ips if x not in candidate_ips]
                if len(cmp_ips) == 0:
                    pvc_port_uuid = pvc_intf._info.get('port_id')
                    break
            else:
                LOG.warning(_('Cannot locate detach port id for pvc server %s'
                              ', because cannot retrieve matched pvc'
                              ' interface for addresses %s from %s'),
                            server_with_pvc_id.id, candidate_ips,
                            pvc_interface_list)
                return

        LOG.debug(_('pvc_port_uuid to be detach: %s'), pvc_port_uuid)
        # get the powervc client server instance from novaclient
        response = server_client_obj.interface_detach(pvc_port_uuid)
        LOG.debug(_('detach response: %s'), response)
        return response

    def set_pvc_id_to_port(self, ctx, local_port_id, pvc_port_id):
        """
        After attach an interface to a server, update the neutorn ports
        to reflect latest ports information to neutron db.
        """
        pvc_id = self._api.set_pvc_id_to_port(ctx, local_port_id, pvc_port_id)
        return pvc_id
