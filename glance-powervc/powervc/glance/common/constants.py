# Copyright 2013, 2018 IBM Corp.

"""
All PowerVC Driver ImageManager Constants
"""

import powervc.common.constants as consts

# Maximum size of a property that can be handled by the v1 Image APIs
MAX_HEADER_LEN_V1 = 8192

# Interval in seconds between periodic image syncs
IMAGE_PERIODIC_SYNC_INTERVAL_IN_SECONDS = 300

# The maximum number of images to return with the v1 image list API call. The
# default is 500 images. If the PowerVC has more than 500 images, this limit
# should be increased to include all images.
IMAGE_LIMIT = 500

# the V2 URI patch value
V2_URI_PATH = 'v2.0'

# The image client service type
CLIENT_SERVICE_TYPE = 'image'

# The image client endpoint type to use
CLIENT_ENDPOINT_TYPE = 'publicURL'

# Image location path
IMAGE_LOCATION_PATH = 'v2/images/'

# List of image create parameters to filter out
IMAGE_CREATE_PARAMS_FILTER = ['id']

# List of image update parameters to filter out
IMAGE_UPDATE_PARAMS_FILTER = ['owner', 'location']

# List of image properties which should have HTML/XML entities unescaped
IMAGE_UNESCAPE_PROPERTIES = ['configuration_strategy']

# List of v2image update parameters to filter out
v2IMAGE_UPDATE_PARAMS_FILTER = IMAGE_UPDATE_PARAMS_FILTER + ['deleted',
                                                             'size',
                                                             'checksum']

# List of image properties to filter out during an update
IMAGE_UPDATE_PROPERTIES_FILTER = [consts.POWERVC_UUID_KEY,
                                  consts.LOCAL_UUID_KEY]

# Timestamp format of image updated_at field
IMAGE_TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S'

# The expiration period for image events in hours
EVENT_TUPLE_EXPIRATION_PERIOD_IN_HOURS = 1

# The number of seconds in an hour
SECONDS_IN_HOUR = 3600

# PowerVC identifier
POWER_VC = 'pvc'

# Local hosting OS identifier
LOCAL = 'local'

# Event queue event constants
EVENT_TYPE = 'type'
EVENT_CONTEXT = 'context'
EVENT_MESSAGE = 'message'
EVENT_PAYLOAD = 'payload'
REAL_EVENT_TYPE = 'real_type'
REAL_EVENT_CONTEXT = 'ctxt'

# Event queue event types
LOCAL_IMAGE_EVENT = LOCAL
PVC_IMAGE_EVENT = POWER_VC
PERIODIC_SCAN_EVENT = 'periodic'
STARTUP_SCAN_EVENT = 'startup'

# Image notification event exchange
IMAGE_EVENT_EXCHANGE = 'glance'

# Image notification event topic
IMAGE_EVENT_TOPIC = 'notifications'

# Image notification event types
IMAGE_EVENT_TYPE_ALL = 'image.*'
IMAGE_EVENT_TYPE_ACTIVATE = 'image.activate'
IMAGE_EVENT_TYPE_CREATE = 'image.create'
IMAGE_EVENT_TYPE_UPDATE = 'image.update'
IMAGE_EVENT_TYPE_DELETE = 'image.delete'

# Constants used by the ImageSyncController
SYNC_PASSED = 1
SYNC_FAILED = -1
IMAGE_SYNC_RETRY_INTERVAL_TIME_IN_SECONDS = 60
IMAGE_SYNC_CHECK_INTERVAL_TIME_IN_SECONDS = 1

# Block Device Mapping Key in image properties
BDM_KEY = 'block_device_mapping'

V1_PROPERTIES = ['os_distro', 'block_device_mapping', 'hypervisor_type',
                 'bdm_v2', 'architecture', 'endianness', 'root_device_name']
