COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
PowerVC Driver Common Exceptions
"""

from powervc.common.gettextutils import _

_FATAL_EXCEPTION_FORMAT_ERRORS = False


class CommonException(Exception):
    """
    PowerVC Driver Common Exception

    To correctly use this class, inherit from it and define a 'message'
    property. That message will get printed with the keyword arguments
    provided to the constructor.
    """
    message = _('An unknown exception occurred')

    def __init__(self, message=None, *args, **kwargs):
        if not message:
            message = self.message
        try:
            message = message % kwargs
        except Exception:
            if _FATAL_EXCEPTION_FORMAT_ERRORS:
                raise
            else:
                # at least get the core message out if something happened
                pass

        super(CommonException, self).__init__(message)


class StorageConnectivityGroupNotFound(CommonException):
    """
    Exception thrown when the PowerVC Storage Connectivity Group specified
    cannot be found.

    :param scg: The PowerVC Storage Connectivity Group name or id
    """
    message = _('The PowerVC Storage Connectivity Group \'%(scg)s\' was not '
                'found.')


class StagingProjectNotFound(CommonException):
    """
    Exception thrown when the staging project specified in the conf cannot be
    found.

    :param name: The name of the staging project which was not found.
    """
    message = _('The staging project \'%(name)s\' was not found.')


class StagingUserNotFound(CommonException):
    """
    Exception thrown when the staging user specified in the conf cannot be
    found.

    :param name: The name of the staging user which was not found.
    """
    message = _('The staging user \'%(name)s\' was not found.')
