# Copyright 2013 IBM Corp.

"""
All constants.
"""
# Instance metadata keys that will store pvc related infor.
# in the local nova DB.
PVC_ID = "pvc_id"  # pvc instance uuid

PPC64 = "ppc64"  # Found on the wiki

# hypervisor type
PVM_HYPERVISOR_TYPE = "powervm"

# Flavor constants
SCG_KEY = "powervm:storage_connectivity_group"
STORAGE_TEMPLATE_KEY = "powervm:boot_volume_type"
EXTRA_SPECS = "extra_specs"
IS_PUBLIC = "os-flavor-access:is_public"

POWERVC_SUPPORTED_INSTANCES = [('ppc64', 'powervm', 'hvm'),
                               ('ppc64', 'phyp', 'hvm')]

# Suffix to append to sync event notifications
SYNC_EVENT_SUFFIX = 'sync'

# PowerVC instance notification events that we listen for
EVENT_INSTANCE_UPDATE = 'compute.instance.update'
EVENT_INSTANCE_CREATE = 'compute.instance.create.end'
EVENT_INSTANCE_DELETE = 'compute.instance.delete.end'
EVENT_INSTANCE_POWER_ON = 'compute.instance.power_on.end'
EVENT_INSTANCE_POWER_OFF = 'compute.instance.power_off.end'
EVENT_INSTANCE_RESIZE = 'compute.instance.finish_resize.end'
EVENT_INSTANCE_RESIZE_CONFIRM = 'compute.instance.resize.confirm.end'
EVENT_INSTANCE_LIVE_MIGRATE = 'compute.instance.live_migration.post.dest.end'
EVENT_INSTANCE_LIVE_MIGRATE_ROLLBACK = \
    'compute.instance.live_migration._rollback.end'
EVENT_INSTANCE_SNAPSHOT = 'compute.instance.snapshot.end'
EVENT_INSTANCE_VOLUME_ATTACH = 'compute.instance.volume.attach'
EVENT_INSTANCE_VOLUME_DETACH = 'compute.instance.volume.detach'
EVENT_INSTANCE_IMPORT = 'compute.instance.import.end'

# Volume id to to be updated by periodic sync
INVALID_VOLUME_ID = '00000000-0000-0000-0000-000000000000'

LOCAL_PVC_PREFIX = 'powervm:'

HYPERVISOR_PROP_NAME = 'OS-EXT-SRV-ATTR:hypervisor_hostname'
HOST_PROP_NAME = 'OS-EXT-SRV-ATTR:host'


def gen_pvc_key(key):
    if key is None:
        return key
    if key.startswith(LOCAL_PVC_PREFIX):
        return key
    return LOCAL_PVC_PREFIX + key


def parse_pvc_key(pvc_key):
    if pvc_key is None:
        return pvc_key
    if not pvc_key.startswith(LOCAL_PVC_PREFIX):
        return pvc_key
    return pvc_key[len(LOCAL_PVC_PREFIX):]
