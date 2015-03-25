# Copyright 2013 IBM Corp.

import sys
import time
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
from neutron.openstack.common import rpc
from neutron.openstack.common.rpc import dispatcher
from oslo_log import log as logging
from powervc.common.gettextutils import _
from neutron import context

from powervc.common import config

LOG = logging.getLogger(__name__)


class RpcListener(object):

    # Set RPC API version to 1.0 by default.
    RPC_API_VERSION = '1.0'

    def __init__(self):
        LOG.info(_('__init__'))
        self._setup_rpc()

    def _setup_rpc(self):
        LOG.info(_('_setup_rpc'))
        self.topic = 'powervcrpc'

        # RPC network init
        self.context = context.get_admin_context_without_session()

        # Handle updates from service
        self.dispatcher = self._create_rpc_dispatcher()

        # Set up RPC connection
        self.conn = rpc.create_connection(new=True)
        self.conn.create_consumer(self.topic, self.dispatcher, fanout=False)
        self.conn.consume_in_thread()

    def _create_rpc_dispatcher(self):
        LOG.info(_('_create_rpc_dispatcher'))
        return dispatcher.RpcDispatcher([self])

    def get_pvc_network_uuid(self, context, network_id):
        LOG.info(_("get_pvc_network_uuid(): network_id: %s"), network_id)
        return '123'

    def daemon_loop(self):
        while True:
            LOG.info(_("Sleeping..."))
            delay = 10
            time.sleep(delay)


def main():
    try:
        config.parse_power_config(sys.argv, 'powervc-neutron')
        logging_config.setup_logging(cfg.CONF)
        agent = RpcListener()
        agent.daemon_loop()
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
