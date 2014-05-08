COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
Module to contain all of the local OS routines
"""

'''
Created on Aug 1, 2013

@author: John Kasperski
'''

from neutron.openstack.common import log as logging

from powervc.common import messaging
from powervc.common.client import factory
from powervc.common.constants import SERVICE_TYPES
from powervc.common.constants import LOCAL_OS
from powervc.common.gettextutils import _
from powervc.neutron.client import neutron_client_bindings
from powervc.neutron.common import constants
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_db_v2

LOG = logging.getLogger(__name__)


class Client(neutron_client_bindings.Client):
    """Local OS access methods"""

    def __init__(self, client, agent):
        if not client:
            return
        self.os = LOCAL_OS
        self.db = powervc_db_v2.PowerVCAgentDB()
        self.agent = agent
        super(Client, self).__init__(client, self.os)
        self._create_amqp_listeners()
        # A cache to save image uuids on power.
        self.power_image_cache = []
        # Save nova/glance client
        self.nova = None
        self.glance = None

    def _create_amqp_listeners(self):
        """Listen for AMQP messages from the local OS"""
        LOG.debug(_('Creating AMQP listeners'))

        def reconnect():
            LOG.info(_('Re-established connection to local OS Qpid broker'))
            self.agent.queue_event(self.os, constants.EVENT_FULL_SYNC, None)

        connection = messaging.LocalConnection(log=logging,
                                               reconnect_handler=reconnect)
        listener = connection.create_listener(constants.QPID_EXCHANGE,
                                              constants.QPID_TOPIC)
        listener.register_handler(constants.EVENT_NETWORK_CREATE,
                                  self._handle_network_create)
        listener.register_handler(constants.EVENT_NETWORK_UPDATE,
                                  self._handle_network_update)
        listener.register_handler(constants.EVENT_NETWORK_DELETE,
                                  self._handle_network_delete)
        listener.register_handler(constants.EVENT_SUBNET_CREATE,
                                  self._handle_subnet_create)
        listener.register_handler(constants.EVENT_SUBNET_UPDATE,
                                  self._handle_subnet_update)
        listener.register_handler(constants.EVENT_SUBNET_DELETE,
                                  self._handle_subnet_delete)
        listener.register_handler(constants.EVENT_PORT_CREATE,
                                  self._handle_port_create)
        listener.register_handler(constants.EVENT_PORT_UPDATE,
                                  self._handle_port_update)
        listener.register_handler(constants.EVENT_PORT_DELETE,
                                  self._handle_port_delete)
        connection.start()

    def _handle_network_create(self, context, message):
        event, payload = self._extact_event_payload(message)
        network = payload.get('network')
        network_id = network.get('id')
        if not utils.is_network_mappable(network):
            LOG.info(_("Network %s is not mappable"), network_id)
            return
        db_net = self.db.get_network(local_id=network_id)
        if db_net:
            LOG.info(_("DB entry for network %s already exists"), network_id)
            return
        self.agent.queue_event(self.os, event, network)

    def _handle_network_update(self, context, message):
        event, payload = self._extact_event_payload(message)
        network = payload.get('network')
        self.agent.queue_event(self.os, event, network)

    def _handle_network_delete(self, context, message):
        event, payload = self._extact_event_payload(message)
        network_id = payload.get('network_id')
        self.agent.queue_event(self.os, event, network_id)

    def _handle_subnet_create(self, context, message):
        event, payload = self._extact_event_payload(message)
        subnet = payload.get('subnet')
        subnet_id = subnet.get('id')
        if not utils.is_subnet_mappable(subnet):
            LOG.info(_("Subnet %s is not mappable"), subnet_id)
            return
        db_sub = self.db.get_subnet(local_id=subnet_id)
        if db_sub:
            LOG.info(_("DB entry for subnet %s already exists"), subnet_id)
            return
        self.agent.queue_event(self.os, event, subnet)

    def _handle_subnet_update(self, context, message):
        event, payload = self._extact_event_payload(message)
        subnet = payload.get('subnet')
        self.agent.queue_event(self.os, event, subnet)

    def _handle_subnet_delete(self, context, message):
        event, payload = self._extact_event_payload(message)
        subnet_id = payload.get('subnet_id')
        self.agent.queue_event(self.os, event, subnet_id)

    def _handle_port_create(self, context, message):
        event, payload = self._extact_event_payload(message)
        port = payload.get('port')
        port_id = port.get('id')
        if not utils.is_port_mappable(port):
            LOG.info(_("Port %s is not mappable"), port_id)
            return
        db_port = self.db.get_port(local_id=port_id)
        if db_port:
            LOG.info(_("DB entry for port %s already exists"), port_id)
            return
        self.agent.queue_event(self.os, event, port)

    def _handle_port_update(self, context, message):
        event, payload = self._extact_event_payload(message)
        port = payload.get('port')
        self.agent.queue_event(self.os, event, port)

    def _handle_port_delete(self, context, message):
        event, payload = self._extact_event_payload(message)
        port_id = payload.get('port_id')
        self.agent.queue_event(self.os, event, port_id)

#==============================================================================
# Local OS - Utility routines using other clients (Nova, Glance)
#==============================================================================

    def get_power_vm_mapping(self):
        """
        Return dict with PowerVC to local instance uuid mappings
        """
        vm_map = {}
        if not self.nova:
            self.nova = factory.LOCAL.get_client(str(SERVICE_TYPES.compute))
        try:
            local_instances = self.nova.manager.list_all_servers()
        except Exception as e:
            LOG.exception(_("Exception occurred getting servers: %s"), e)
            return vm_map
        for inst in local_instances:
            metadata = inst._info.get(constants.METADATA)
            if metadata:
                pvc_id = metadata.get(constants.PVC_ID)
                if pvc_id:
                    vm_map[pvc_id] = inst._info.get('id')
        return vm_map

    def is_instance_valid(self, uuid):
        """
        Check if this VM instance is still valid. Call nova client
        to retrieve the VM information.
        """
        # Verify uuid is valid
        if not uuid or len(uuid) == 0:
            return False
        # Check to see if this is a reserved port that we created while we
        # are waiting for the PowerVC side to go away
        if uuid.startswith(constants.RSVD_PORT_PREFIX):
            return False

        if not self.nova:
            self.nova = factory.LOCAL.get_client(str(SERVICE_TYPES.compute))
        try:
            inst = self.nova.manager.get(uuid)
        except Exception as e:
            """
            If the instance can not be found, exception will be thrown.  These
            exceptions should be caught and not break the agent.
            """
            LOG.exception(_("Exception occurred getting server %s: %s"),
                          uuid, e)
            return False
        if inst:
            return True
        return False

    def is_instance_on_power(self, uuid):
        """
            Return True if an instance is hosted on power.
        """
        # Verify uuid is valid
        if not uuid or len(uuid) == 0:
            return False

        if not self.nova:
            self.nova = factory.LOCAL.get_client(str(SERVICE_TYPES.compute))
        try:
            inst = self.nova.manager.get(uuid)
        except Exception as e:
            """
            If the instance can not be found, exception will be thrown.  These
            exceptions should be caught and not break the agent.
            """
            LOG.exception(_("Exception occurred getting server %s: %s"),
                          uuid, e)
            return False
        if inst:
            metadata = inst._info[constants.METADATA]
            if constants.PVC_ID in metadata:
                # Return true if we have pvc_id for this instance.
                return True
            else:
                img_uuid = inst.image.get('id', '')
                if img_uuid in self.power_image_cache:
                    return True
                else:
                    # Check if the image is hosted on power.
                    if not self.glance:
                        self.glance = factory.LOCAL.\
                            get_client(str(SERVICE_TYPES.image))
                    try:
                        img = self.glance.getImage(img_uuid)
                    except Exception as e:
                        LOG.exception(_("Exception occurred getting image "
                                        "%s: %s"), img_uuid, e)
                        return False
                    if constants.POWERVM == img.get(constants.HYPERVISOR_TYPE,
                                                    ''):
                        self.power_image_cache.append(img_uuid)
                        return True
                    return False
        # Return false if we can't find this instance locally.
        return False
