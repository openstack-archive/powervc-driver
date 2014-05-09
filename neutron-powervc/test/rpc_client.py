# Copyright 2013 IBM Corp.

import sys
import traceback
import os

if ('eventlet' in sys.modules and
        os.environ.get('EVENTLET_NO_GREENDNS', '').lower() != 'yes'):
    raise ImportError('eventlet imported before neutron agent '
                      '(env var set to %s)'
                      % os.environ.get('EVENTLET_NO_GREENDNS'))

os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
import eventlet
eventlet.patcher.monkey_patch(os=False, thread=False)

from oslo.config import cfg

CONF = cfg.CONF

from neutron.common import config as logging_config
from neutron.openstack.common.rpc import proxy
from neutron.openstack.common import log as logging
from powervc.common.gettextutils import _

from neutron import context

from powervc.common import config

LOG = logging.getLogger(__name__)


class RpcClient(proxy.RpcProxy):

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, context):
        LOG.info(_('__init__'))
        self.topic = 'powervcrpc'
        self.context = context
        self.host = cfg.CONF.host
        super(RpcClient, self).__init__(
            topic=self.topic, default_version=self.BASE_RPC_API_VERSION)

    def get_pvc_network_uuid(self, network_id):
        LOG.info(_('get_pvc_network_uuid'))
        result = self.call(self.context,
                           self.make_msg('get_pvc_network_uuid',
                                         network_id=network_id),
                           topic=self.topic)
        return result


def main():
    try:
        config.parse_power_config(sys.argv, 'powervc-neutron')
        logging_config.setup_logging(cfg.CONF)

        LOG.info(_('Create RPC interface'))
        ctx = context.get_admin_context_without_session()
        rpc = RpcClient(ctx)

        LOG.info(_('Calling RPC method'))
        result = rpc.get_pvc_network_uuid('abc')
        LOG.info(_('Result from RPC call: %s'), result)

        sys.exit(0)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
