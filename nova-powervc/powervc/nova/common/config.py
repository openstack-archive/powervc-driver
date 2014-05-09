# Copyright 2013 IBM Corp.

import powervc.common.config as common_config
from nova import rpc
from oslo.config import cfg
from nova import objects

CONF = common_config.CONF

computes_opts = [
    cfg.IntOpt('hypervisor_refresh_interval',
               default=30,
               help=('The number of seconds between hypervisor refreshes.')),
    cfg.IntOpt('instance_sync_interval',
               default=20,
               help=('Instance periodic sync interval specified in '
                     'seconds.')),
    cfg.IntOpt('full_instance_sync_frequency',
               default=30,
               help=('How many instance sync intervals between full instance '
                     'syncs. Only instances known to be out of sync are '
                     'synced on the interval except after this many '
                     'intervals when all instances are synced.')),
    cfg.StrOpt('flavor_prefix', default='PVC-'),
    cfg.ListOpt('flavor_white_list', default=[]),
    cfg.ListOpt('flavor_black_list', default=[]),
    cfg.IntOpt('flavor_sync_interval', default=300),
    cfg.IntOpt('volume_max_try_times', default=12),
    cfg.IntOpt('longrun_loop_interval', default=7),
    cfg.IntOpt('longrun_initial_delay', default=10),
    cfg.IntOpt('image_limit', default=500)
]

CONF.register_opts(computes_opts, group='powervc')

# import nova opts
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('compute_topic', 'nova.compute.rpcapi')
CONF.import_opt('default_availability_zone', 'nova.availability_zones')
CONF.import_opt('compute_driver', 'nova.virt.driver')

objects.register_all()


def parse_config(*args, **kwargs):
    rpc.set_defaults(control_exchange='nova')
    common_config.parse_power_config(*args, **kwargs)
    rpc.init(CONF)
