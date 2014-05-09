# Copyright 2013 IBM Corp.

from nova import exception
from powervc.common.gettextutils import _


class BlockMigrationException(exception.NovaException):
    """User attempted to perform live migration with block migration."""
    def __init__(self):
        message = _("PowerVC does not support block migration.")
        super(BlockMigrationException, self).__init__(message=message)
