# Copyright 2013 IBM Corp.


import sys
import traceback
import powervc.nova.common.config as config
from nova.openstack.common import log
from nova import service
from nova import utils


def main():
    CONF = config.CONF
    try:
        config.parse_config(sys.argv, 'nova')
        log.setup('powervc')
        utils.monkey_patch()
        server = service.Service.create(manager=CONF.powervc.powervc_manager,
                                        binary='nova-powervc')
        service.serve(server)
        service.wait()
    except Exception:
        traceback.print_exc()
        raise
