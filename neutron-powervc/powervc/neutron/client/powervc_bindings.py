COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
Module to contain all of the PowerVC routines
"""

'''
Created on Aug 1, 2013

@author: John Kasperski
'''

from neutron.openstack.common import log as logging

from powervc.common import messaging
from powervc.common.constants import POWERVC_OS
from powervc.common.gettextutils import _
from powervc.neutron.client import neutron_client_bindings
from powervc.neutron.common import constants
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_db_v2

LOG = logging.getLogger(__name__)


class Client(neutron_client_bindings.Client):
    """PowerVC access methods"""

    def __init__(self, client, agent):
        if not client:
            return
        self.os = POWERVC_OS
        self.db = powervc_db_v2.PowerVCAgentDB()
        self.agent = agent
        super(Client, self).__init__(client, self.os)
        self._create_amqp_listeners()

    def _create_amqp_listeners(self):
        """Listen for AMQP messages from PowerVC"""
        LOG.debug(_('Creating AMQP listeners'))

        def reconnect():
            LOG.info(_('Re-established connection to PowerVC Qpid broker'))
            self.agent.queue_event(self.os, constants.EVENT_FULL_SYNC, None)

        connection = messaging.PowerVCConnection(log=logging,
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
        db_net = self.db.get_network(pvc_id=network_id)
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
        db_sub = self.db.get_subnet(pvc_id=subnet_id)
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
        db_port = self.db.get_port(pvc_id=port_id)
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
