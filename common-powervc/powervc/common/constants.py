# Copyright 2013 IBM Corp.

"""
All Common PowerVC Driver Constants
"""

# The user domain default value
DEFAULT_USER_DOMAIN_NAME = 'Default'

# The project domain default value
DEFAULT_PROJECT_DOMAIN_NAME = 'Default'

# The default staging project name
DEFAULT_STAGING_PROJECT_NAME = 'Public'

# The default staging user name
DEFAULT_STAGING_USER_NAME = 'admin'

# The property key used to store a PowerVC resource UUID in
# a hosting OS resource.
POWERVC_UUID_KEY = 'powervc_uuid'

# The property key used to mark a powervc image with the
# corresponding powervc driver image uuid.
LOCAL_UUID_KEY = 'powervcdriver_uuid'

# OpenStack instance identifier
LOCAL_OS = 'local'
POWERVC_OS = 'powervc'

# AMQP topic for the commun. between nova and neutron
PVC_TOPIC = 'powervcrpc'

# Storage Type that SCG can access
SCG_SUPPORTED_STORAGE_TYPE = 'fc'


class ServiceType(object):
    """Wrappers service type to project codename.
    """
    def __init__(self, svc_type, codename):
        self.svc_type = svc_type
        self.codename = codename

    def __str__(self):
        return self.svc_type

    def to_codename(self):
        """Returns the codename of this service.
        """
        return self.codename


class ServiceTypes(object):
    """The service types known to this infrastructure which can be
    referenced using attr based notation.
    """
    def __init__(self):
        self.volume = ServiceType('volume', 'cinder')
        self.volumev2 = ServiceType('volumev2', 'cinder')
        self.compute = ServiceType('compute', 'nova')
        self.network = ServiceType('network', 'neutron')
        self.identity = ServiceType('identity', 'keystone')
        self.computev3 = ServiceType('computev3', 'nova')
        self.image = ServiceType('image', 'glance')
        self.s3 = ServiceType('s3', 'nova')
        self.ec2 = ServiceType('ec2', 'nova'),
        self.ttv = ServiceType('ttv', 'ttv')

    def __getitem__(self, name):
        if name in self.__dict__:
            return self.__dict__[name]
        return None

SERVICE_TYPES = ServiceTypes()
