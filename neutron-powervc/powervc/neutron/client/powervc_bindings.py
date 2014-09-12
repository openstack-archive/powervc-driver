# Copyright 2013 IBM Corp.

"""
Module to contain all of the PowerVC routines
"""

'''
Created on Aug 1, 2013

@author: John Kasperski
'''

from neutron.openstack.common import log as logging

from powervc.common.constants import POWERVC_OS
from powervc.common.gettextutils import _
from powervc.neutron.client import neutron_client_bindings
from powervc.neutron.common import constants
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_db_v2

from powervc.common import config as cfg
from powervc.common import messaging

from oslo.messaging.notify import listener
from oslo.messaging import target
from oslo.messaging import transport

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
        """Listen for AMQP messages from PowerVC."""

        LOG.debug("Entry _create_amqp_listeners(pvc) method")

        trans = transport.get_transport(cfg.AMQP_POWERVC_CONF)
        targets = [
            target.Target(exchange=constants.QPID_EXCHANGE,
                          topic=constants.QPID_TOPIC)
        ]
        endpoint = messaging.NotificationEndpoint(log=LOG)

        endpoint.register_handler(constants.EVENT_NETWORK_CREATE,
                                  self._handle_network_create)
        endpoint.register_handler(constants.EVENT_NETWORK_UPDATE,
                                  self._handle_network_update)
        endpoint.register_handler(constants.EVENT_NETWORK_DELETE,
                                  self._handle_network_delete)
        endpoint.register_handler(constants.EVENT_SUBNET_CREATE,
                                  self._handle_subnet_create)
        endpoint.register_handler(constants.EVENT_SUBNET_UPDATE,
                                  self._handle_subnet_update)
        endpoint.register_handler(constants.EVENT_SUBNET_DELETE,
                                  self._handle_subnet_delete)
        endpoint.register_handler(constants.EVENT_PORT_CREATE,
                                  self._handle_port_create)
        endpoint.register_handler(constants.EVENT_PORT_UPDATE,
                                  self._handle_port_update)
        endpoint.register_handler(constants.EVENT_PORT_DELETE,
                                  self._handle_port_delete)

        endpoints = [
            endpoint,
        ]

        LOG.debug("Starting to listen...... ")

        pvc_neutron_listener = listener.\
            get_notification_listener(trans, targets, endpoints,
                                      allow_requeue=False)
        pvc_neutron_listener.start()
        pvc_neutron_listener.wait()

        LOG.debug("Exit _create_amqp_listeners(pvc) method")

    def _handle_network_create(self,
                               context=None,
                               ctxt=None,
                               event_type=None,
                               payload=None):

        network = payload.get('network')
        network_id = network.get('id')
        if not utils.is_network_mappable(network):
            LOG.info(_("Network %s is not mappable"), network_id)
            return
        db_net = self.db.get_network(pvc_id=network_id)
        if db_net:
            LOG.info(_("DB entry for network %s already exists"), network_id)
            return
        self.agent.queue_event(self.os, event_type, network)

    def _handle_network_update(self,
                               context=None,
                               ctxt=None,
                               event_type=None,
                               payload=None):

        network = payload.get('network')
        self.agent.queue_event(self.os, event_type, network)

    def _handle_network_delete(self,
                               context=None,
                               ctxt=None,
                               event_type=None,
                               payload=None):

        network_id = payload.get('network_id')
        self.agent.queue_event(self.os, event_type, network_id)

    def _handle_subnet_create(self,
                              context=None,
                              ctxt=None,
                              event_type=None,
                              payload=None):

        subnet = payload.get('subnet')
        subnet_id = subnet.get('id')
        if not utils.is_subnet_mappable(subnet):
            LOG.info(_("Subnet %s is not mappable"), subnet_id)
            return
        db_sub = self.db.get_subnet(pvc_id=subnet_id)
        if db_sub:
            LOG.info(_("DB entry for subnet %s already exists"), subnet_id)
            return
        self.agent.queue_event(self.os, event_type, subnet)

    def _handle_subnet_update(self,
                              context=None,
                              ctxt=None,
                              event_type=None,
                              payload=None):

        subnet = payload.get('subnet')
        self.agent.queue_event(self.os, event_type, subnet)

    def _handle_subnet_delete(self,
                              context=None,
                              ctxt=None,
                              event_type=None,
                              payload=None):

        subnet_id = payload.get('subnet_id')
        self.agent.queue_event(self.os, event_type, subnet_id)

    def _handle_port_create(self,
                            context=None,
                            ctxt=None,
                            event_type=None,
                            payload=None):

        port = payload.get('port')
        port_id = port.get('id')
        if not utils.is_port_mappable(port):
            LOG.info(_("Port %s is not mappable"), port_id)
            return
        db_port = self.db.get_port(pvc_id=port_id)
        if db_port:
            LOG.info(_("DB entry for port %s already exists"), port_id)
            return
        self.agent.queue_event(self.os, event_type, port)

    def _handle_port_update(self,
                            context=None,
                            ctxt=None,
                            event_type=None,
                            payload=None):

        port = payload.get('port')
        self.agent.queue_event(self.os, event_type, port)

    def _handle_port_delete(self,
                            context=None,
                            ctxt=None,
                            event_type=None,
                            payload=None):

        port_id = payload.get('port_id')
        self.agent.queue_event(self.os, event_type, port_id)
