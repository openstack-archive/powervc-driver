# Copyright 2013 IBM Corp.

"""
PowerVC Driver ImageManager Configuration
"""

from oslo.config import cfg
import powervc.common.config as common_config
from powervc.glance.common import constants

CONF = common_config.CONF

# PowerVC Driver ImageManager specific configuration
image_opts = [

    # The image periodic sync interval in seconds. Default is 300.
    cfg.IntOpt('image_periodic_sync_interval_in_seconds',
               default=constants.IMAGE_PERIODIC_SYNC_INTERVAL_IN_SECONDS),

    # In case of error, the image sync retry interval time in seconds. Default
    # is 60.
    cfg.IntOpt('image_sync_retry_interval_time_in_seconds',
               default=constants.IMAGE_SYNC_RETRY_INTERVAL_TIME_IN_SECONDS),

    # The maximum number of images to read for each query request. Default is
    # 500.
    cfg.IntOpt('image_limit', default=constants.IMAGE_LIMIT)
]

CONF.register_opts(image_opts, group='powervc')

"""
Refer to the file glance/api/middleware/context.py , register the config
option named 'owner_is_tenant' to default group.
"""
CONF.register_opt(cfg.BoolOpt('owner_is_tenant', default=True,
                              help=_('When true, this option sets the owner of '
                                     'an image to be the tenant. Otherwise, the'
                                     ' owner of the image will be the '
                                     'authenticated user issuing the request.')))


def parse_config(*args, **kwargs):
    common_config.parse_power_config(*args, **kwargs)
