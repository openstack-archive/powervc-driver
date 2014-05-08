COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
All constants.
"""
# Instance metadata keys that will store pvc related infor.
# in the local nova DB.
PVC_TENANT = "pvc_tenant"  # project in pvc
PVC_SCG = "pvc_scg"  # pvc storage connection group
PVC_ID = "pvc_id"  # pvc instance uuid

PPC64 = "ppc64"  # Found on the wiki
# The default image for pvc instance if no match found.
DEFAULT_IMG = "SCE Default Image"
DEFAULT_SCG = "storage connection group"

# Suffix to append to sync event notifications
SYNC_EVENT_SUFFIX = 'sync'

LOCAL_PVC_VOLUME_TYPE_PREFIX = 'pvc:'

LOCAL_PVC_PREFIX = 'pvc:'

# The composite PowerVC storage backend
POWERVC_VOLUME_BACKEND = 'powervc'

# PowerVC volume & volume type notification events that we listen for
EVENT_VOLUME_TYPE_CREATE = 'volume_type.create'
EVENT_VOLUME_TYPE_DELETE = 'volume_type.delete'
EVENT_VOLUME_TYPE_EXTRA_SPECS_CREATE = 'volume_type_extra_specs.create'
EVENT_VOLUME_TYPE_EXTRA_SPECS_UPDATE = 'volume_type_extra_specs.update'
EVENT_VOLUME_TYPE_EXTRA_SPECS_DELETE = 'volume_type_extra_specs.delete'

EVENT_VOLUME_CREATE_START = 'volume.create.start'
EVENT_VOLUME_CREATE_END = 'volume.create.end'
EVENT_VOLUME_DELETE_START = 'volume.delete.start'
EVENT_VOLUME_DELETE_END = 'volume.delete.end'
EVENT_VOLUME_UPDATE = 'volume.update'
EVENT_VOLUME_ATTACH_START = 'volume.attach.start'
EVENT_VOLUME_ATTACH_END = 'volume.attach.end'
EVENT_VOLUME_DETACH_START = 'volume.detach.start'
EVENT_VOLUME_DETACH_END = 'volume.detach.end'
EVENT_VOLUME_IMPORT_START = 'volume.import.start'
EVENT_VOLUME_IMPORT_END = 'volume.import.end'

# PowerVC volume operation status
STATUS_AVAILABLE = 'available'
STATUS_ERROR = 'error'
STATUS_CREATING = 'creating'
STATUS_DELETING = 'deleting'

#multi-backends configuration option for PowerVCDriver
BACKEND_POWERVCDRIVER = "powervcdriver"
