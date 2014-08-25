# Copyright 2013 IBM Corp.

from prettytable import PrettyTable

from powervc.common import config

from oslo.config import cfg

from neutron.common.rpc import RpcProxy
from neutron.common import rpc
from neutron.openstack.common import log as logging

from powervc.common.gettextutils import _

LOG = logging.getLogger(__name__)
LIST_COLUMNS = ['status', 'local_id', 'pvc_id', 'sync_key']


#==============================================================================
# RPC client
#==============================================================================

class RpcClient(RpcProxy):

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, context):
        LOG.debug(_('__init__'))
        self.topic = 'powervcrpc'
        self.context = context
        self.host = cfg.CONF.host
        rpc.init(config.AMQP_OPENSTACK_CONF)
        super(RpcClient, self).__init__(
            topic=self.topic, default_version=self.BASE_RPC_API_VERSION)

    def _print_table(self, result):
        if result and len(result) > 0:
            pt = PrettyTable(LIST_COLUMNS)
            for obj in result:
                row = []
                for col in LIST_COLUMNS:
                    row.append(obj.get(col))
                pt.add_row(row)
            print pt

    def _print_object(self, result):
        if result:
            pt = PrettyTable(['Field', 'Value'])
            pt.align['Field'] = 'l'
            pt.align['Value'] = 'l'
            for field in result.keys():
                row = [field, result.get(field)]
                pt.add_row(row)
            print pt
        else:
            print 'Result from RPC call: ', result

    def get_local_network_uuid(self, network_id):
        LOG.debug(_('get_local_network_uuid'))
        result = self.call(self.context,
                           self.make_msg('get_local_network_uuid',
                                         network_id=network_id),
                           topic=self.topic)
        print 'Result from RPC call:', result

    def get_pvc_network_uuid(self, network_id):
        LOG.debug(_('get_pvc_network_uuid'))
        result = self.call(self.context,
                           self.make_msg('get_pvc_network_uuid',
                                         network_id=network_id),
                           topic=self.topic)
        print 'Result from RPC call:', result

    def get_pvc_port_uuid(self, port_id):
        LOG.debug(_('get_pvc_port_uuid'))
        result = self.call(self.context,
                           self.make_msg('get_pvc_port_uuid',
                                         port_id=port_id),
                           topic=self.topic)
        print 'Result from RPC call:', result

    def get_network(self, opt):
        LOG.debug(_('get_network: %s'), opt)
        result = self.call(self.context,
                           self.make_msg('get_network', sync_key=opt),
                           topic=self.topic)
        self._print_object(result)

    def get_networks(self):
        LOG.debug(_('get_networks'))
        result = self.call(self.context,
                           self.make_msg('get_networks'),
                           topic=self.topic)
        self._print_table(result)

    def get_subnet(self, opt):
        LOG.debug(_('get_subnet: %s'), opt)
        result = self.call(self.context,
                           self.make_msg('get_subnet', sync_key=opt),
                           topic=self.topic)
        self._print_object(result)

    def get_subnets(self):
        LOG.debug(_('get_subnets'))
        result = self.call(self.context,
                           self.make_msg('get_subnets'),
                           topic=self.topic)
        self._print_table(result)

    def get_port(self, opt):
        LOG.debug(_('get_port: %s'), opt)
        result = self.call(self.context,
                           self.make_msg('get_port', sync_key=opt),
                           topic=self.topic)
        self._print_object(result)

    def get_ports(self):
        LOG.debug(_('get_ports'))
        result = self.call(self.context,
                           self.make_msg('get_ports'),
                           topic=self.topic)
        self._print_table(result)
