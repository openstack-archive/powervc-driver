# Copyright 2013 IBM Corp.

'''
Created on Aug 2, 2013

@author: John Kasperski
'''

# ==============================================================================
# Device owner value for Neutron ports we create
# ==============================================================================
POWERVC_DEVICE_OWNER = 'network:IBM SmartCloud'
RSVD_PORT_PREFIX = 'pvc:'

# ==============================================================================
# Mapping enum values
# ==============================================================================

OBJ_TYPE_NETWORK = 'Network'
OBJ_TYPE_SUBNET = 'Subnet'
OBJ_TYPE_PORT = 'Port'

STATUS_CREATING = 'Creating'
STATUS_ACTIVE = 'Active'
STATUS_DELETING = 'Deleting'

MAX_UPDATE_DATA_LENGTH = 512

# ==============================================================================
# Neutron network fields (that we care about)
# ==============================================================================

NETWORK_CREATE_FIELDS = ['name',
                         'shared',
                         'provider:network_type',
                         'provider:segmentation_id',
                         'provider:physical_network']
NETWORK_UPDATE_FIELDS = ['name',
                         'shared']

# ==============================================================================
# Neutron subnet fields (that we care about)
# ==============================================================================

SUBNET_CREATE_FIELDS = ['name',
                        'ip_version',
                        'cidr',
                        'gateway_ip',
                        'dns_nameservers',
                        'allocation_pools',
                        'enable_dhcp']
SUBNET_UPDATE_FIELDS = ['name',
                        'gateway_ip',
                        'dns_nameservers',
                        'enable_dhcp']

# ==============================================================================
# Neutron port fields (that we care about)
# ==============================================================================

PORT_CREATE_FIELDS = ['name',
                      'mac_address',
                      'device_owner']
PORT_UPDATE_FIELDS = ['name']

# ==============================================================================
# Qpid message handling
# ==============================================================================

QPID_EXCHANGE = 'neutron'
QPID_TOPIC = 'notifications.info'

EVENT_END_THREAD = 'thread.end'
EVENT_FULL_SYNC = 'full.sync'

EVENT_NETWORK_CREATE = 'network.create.end'
EVENT_NETWORK_UPDATE = 'network.update.end'
EVENT_NETWORK_DELETE = 'network.delete.end'

EVENT_SUBNET_CREATE = 'subnet.create.end'
EVENT_SUBNET_UPDATE = 'subnet.update.end'
EVENT_SUBNET_DELETE = 'subnet.delete.end'

EVENT_PORT_CREATE = 'port.create.end'
EVENT_PORT_UPDATE = 'port.update.end'
EVENT_PORT_DELETE = 'port.delete.end'

# Event queue event constants
EVENT_OS = 'os'
EVENT_TYPE = 'type'
EVENT_OBJECT = 'obj'

# metadata key for pvc uuid
METADATA = 'metadata'
PVC_ID = 'pvc_id'

# power image hypervisor type
POWERVM = 'powervm'
HYPERVISOR_TYPE = 'hypervisor_type'
