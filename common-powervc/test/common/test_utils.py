# Copyright 2013 IBM Corp.

import sys
import eventlet
import mock
import testtools
from novaclient.tests.v1_1 import fakes as novafakes
from cinderclient.tests.v1 import fakes as cinderfakes
from novaclient.tests import utils
from powervc.common import utils as pvc_utils
from powervc.common.client.extensions import nova as ext_nova
from powervc.common.client.extensions import cinder as ext_cinder
from powervc.common.client import delegate
from powervc.common import config
from powervc.common.utils import SCGCache
from powervc.common.utils import VolumeCache

sys.modules['powervc.common.config'] = mock.MagicMock()


"""
    This class similarly extend the current nova client test cases
    and cinder client testcases to provide powervc specified
    storage-connectivity-group, storage template and volume related testcases

    To run the testcases, alternatively:
    1. Right click the TestNovaClient.py --> Run As --> Python unit-test
    or
    2. Refer to this link for detail UT running information:
    https://jazz04.rchland.ibm.com:9443/jazz/service/ +
    com.ibm.team.workitem.common.internal.rest.IAttachmentRestService/ +
    itemName/com.ibm.team.workitem.Attachment/67843

    The UtilsRealTest connect to real PowerVC v1.2 and retrieve information.
    This cases might be fail due to real environment unavailable, all other
    fake testcases should be run successfully.
"""


class PVCFakeNovaClient(novafakes.FakeClient):

    """
        This PVCFakeClient class extends the current nova FakeClient,
        aiming to set the self.client variable to PVCFakeHTTPClient
    """

    def __init__(self, *args, **kwargs):
        novafakes.FakeClient.__init__(self, *args, **kwargs)
        self.client = PVCFakeNovaHTTPClient(**kwargs)


class PVCFakeNovaHTTPClient(novafakes.FakeHTTPClient):

    """
        This PVCFakeHTTPClient class extends the current nova FakeHTTPClient.
        For all the HTTP requests in this class, it returns a fake json data
        as specified beforehand instead of requesting to a real environment.
    """

    def __init__(self, **kwargs):
        novafakes.FakeHTTPClient.__init__(self, **kwargs)

    def get_servers_detail(self, **kw):
        return (200, {}, {
            "servers": [
                {
                    "OS-EXT-STS:task_state": "activating",
                    "addresses": {
                        "VLAN1": [
                            {
                                "version": 4,
                                "addr": "10.4.11.113",
                                "OS-EXT-IPS:type": "fixed"
                            }
                        ]
                    },
                    "image": {
                        "id": "fd2a0fdc-fcda-45fc-b5dd-96b9d9e0aa4d",
                        "links": [
                            {
                                "href": "https://localhost/powervc/openstack/\
                                compute/2ec48b8ec30f4328bf95b8a5ad147c4b/\
                                images/fd2a0fdc-fcda-45fc-b5dd-96b9d9e0aa4d",
                                "rel": "bookmark"
                            }
                        ]
                    },
                    "ephemeral_gb": 1,
                    "cpus": "1",
                    "flavor": {
                        "id": "726544ff-9f0a-41ad-8b26-e6575bfe8146",
                        "links": [
                            {
                                "href": "https://localhost/powervc/openstack/\
                                compute/2ec48b8ec30f4328bf95b8a5ad147c4b/\
                                flavors/726544ff-9f0a-41ad-8b26-e6575bfe8146",
                                "rel": "bookmark"
                            }
                        ]
                    },
                    "user_id": "8a326a8c5a774022a1ec49f5692bc316",
                    "vcpu_mode": "shared",
                    "desired_compatibility_mode": "default",
                    "updated": "2013-09-04T07:09:33Z",
                    "memory_mode": "dedicated",
                    "key_name": None,
                    "min_memory_mb": 512,
                    "name": "hc-22",
                    "min_vcpus": "0.10",
                    "vcpus": "0.50",
                    "max_memory_mb": 4096,
                    "min_cpus": "1",
                    "links": [
                        {
                            "href": "https://localhost/powervc/openstack/\
                            compute/\
                            v2/2ec48b8ec30f4328bf95b8a5ad147c4b/servers/\
                            6e205d64-7651-42bf-9c8b-b0cb4208e813",
                            "rel": "self"
                        },
                        {
                            "href": "https://localhost/powervc/openstack/\
                            compute/\
                            2ec48b8ec30f4328bf95b8a5ad147c4b/servers/\
                            6e205d64-7651-42bf-9c8b-b0cb4208e813",
                            "rel": "bookmark"
                        }
                    ],
                    "max_vcpus": "16.00",
                    "OS-EXT-STS:vm_state": "active",
                    "OS-EXT-SRV-ATTR:instance_name":
                    "nova-z3-9-5-125-55-00000075",
                    "OS-EXT-SRV-ATTR:host": "ngp01_03_vios_1",
                    "id": "6e205d64-7651-42bf-9c8b-b0cb4208e813",
                    "security_groups": [
                        {
                            "name": "default"
                        }
                    ],
                    "OS-DCF:diskConfig": "MANUAL",
                    "health_status": {
                        "health_value": "UNKNOWN",
                        "unknown_reason":
                        "Unable to get related hypervisor data"
                    },
                    "accessIPv4": "",
                    "accessIPv6": "",
                    "progress": 0,
                    "OS-EXT-STS:power_state": 1,
                    "OS-EXT-AZ:availability_zone": "nova",
                    "metadata": {},
                    "status": "ACTIVE",
                    "hostId":
                    "db8f3c353837a52c3782b4d04a767b33bd7dfa72983b4ab9aef91cb0",
                    "cpu_utilization": 0,
                    "compliance_status": [
                        {
                            "status": "compliant",
                            "category": "resource.allocation"
                        }
                    ],
                    "current_compatibility_mode": "POWER7",
                    "root_gb": 4,
                    "OS-EXT-SRV-ATTR:hypervisor_hostname":
                    "ngp01-03-vios-1.rtp.stglabs.ibm.com",
                    "created": "2013-09-04T07:08:31Z",
                    "tenant_id": "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "memory_mb": 512,
                    "max_cpus": "16"
                },
                {
                    "OS-EXT-STS:task_state": "activating",
                    "addresses": {
                        "VLAN1": [
                            {
                                "version": 4,
                                "addr": "10.4.11.112",
                                "OS-EXT-IPS:type": "fixed"
                            }
                        ]
                    },
                    "image": {
                        "id": "fd2a0fdc-fcda-45fc-b5dd-96b9d9e0aa4d",
                        "links": [
                            {
                                "href": "https://localhost/powervc/openstack/\
                                compute/2ec48b8ec30f4328bf95b8a5ad147c4b/\
                                images/\
                                fd2a0fdc-fcda-45fc-b5dd-96b9d9e0aa4d",
                                "rel": "bookmark"
                            }
                        ]
                    },
                    "ephemeral_gb": 1,
                    "cpus": "1",
                    "flavor": {
                        "id": "726544ff-9f0a-41ad-8b26-e6575bfe8146",
                        "links": [
                            {
                                "href": "https://localhost/powervc/openstack/\
                                compute/2ec48b8ec30f4328bf95b8a5ad147c4b/\
                                flavors/726544ff-9f0a-41ad-8b26-e6575bfe8146",
                                "rel": "bookmark"
                            }
                        ]
                    },
                    "user_id": "8a326a8c5a774022a1ec49f5692bc316",
                    "vcpu_mode": "shared",
                    "desired_compatibility_mode": "default",
                    "updated": "2013-09-04T07:02:57Z",
                    "memory_mode": "dedicated",
                    "key_name": None,
                    "min_memory_mb": 512,
                    "name": "hc-11",
                    "min_vcpus": "0.10",
                    "vcpus": "0.50",
                    "max_memory_mb": 4096,
                    "min_cpus": "1",
                    "links": [
                        {
                            "href": "https://localhost/powervc/openstack/\
                            compute\
                            /v2/2ec48b8ec30f4328bf95b8a5ad147c4b/servers/\
                            2eab7ee2-62eb-4f31-8628-20f8b06df86a",
                            "rel": "self"
                        },
                        {
                            "href": "https://localhost/powervc/openstack/\
                            compute/2ec48b8ec30f4328bf95b8a5ad147c4b/\
                            servers/2eab7ee2-62eb-4f31-8628-20f8b06df86a",
                            "rel": "bookmark"
                        }
                    ],
                    "max_vcpus": "16.00",
                    "OS-EXT-STS:vm_state": "active",
                    "OS-EXT-SRV-ATTR:instance_name":
                    "nova-z3-9-5-125-55-00000074",
                    "OS-EXT-SRV-ATTR:host": "ngp01_02_vios_1",
                    "id": "2eab7ee2-62eb-4f31-8628-20f8b06df86a",
                    "security_groups": [
                        {
                            "name": "default"
                        }
                    ],
                    "OS-DCF:diskConfig": "MANUAL",
                    "health_status": {
                        "health_value": "UNKNOWN",
                        "unknown_reason":
                        "Unable to get related hypervisor data"
                    },
                    "accessIPv4": "",
                    "accessIPv6": "",
                    "progress": 0,
                    "OS-EXT-STS:power_state": 1,
                    "OS-EXT-AZ:availability_zone": "nova",
                    "metadata": {},
                    "status": "ACTIVE",
                    "hostId":
                    "a67be7805b2dccafc012b2225f59cbad7504e8716c0fd4631bb6af73",
                    "cpu_utilization": 0.02,
                    "compliance_status": [
                        {
                            "status": "compliant",
                            "category": "resource.allocation"
                        }
                    ],
                    "current_compatibility_mode": "POWER7",
                    "root_gb": 4,
                    "OS-EXT-SRV-ATTR:hypervisor_hostname":
                    "ngp01-02-vios-1.rtp.stglabs.ibm.com",
                    "created": "2013-09-04T07:01:10Z",
                    "tenant_id": "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "memory_mb": 512,
                    "max_cpus": "16"
                }
                ]
        })

    def get_storage_connectivity_groups_f4b541cb(
            self, **kw):
        """
        To get a fake detail storage_connectivity_group
        """
        return (200, {}, {"storage_connectivity_group":
                          {
                              "auto_add_vios": True,
                              "fc_storage_access": False,
                              "display_name": "Auto-SCG for Registered SAN",
                              "vios_cluster":
                              {
                                  "provider_id": "shared_v7000_1"
                              },
                              "host_list": [
                                  {
                                      "name": "ngp01_02_vios_1",
                                      "vios_list": [
                                          {
                                              "lpar_id": 1,
                                              "name": "10-F715A",
                                              "id": "ngp01_02_vios_1##1"
                                          }
                                      ]
                                  },
                                  {
                                      "name": "ngp01_03_vios_1",
                                      "vios_list": [
                                          {
                                              "lpar_id": 1,
                                              "name": "10-F76CA",
                                              "id": "ngp01_03_vios_1##1"
                                          }
                                      ]
                                  }
                              ],
                              "created_at": "2013-08-23 14:56:11.787465",
                              "enabled": True,
                              "auto_defined": True,
                              "id": "f4b541cb"
                          }})

    def get_storage_connectivity_groups_sdfb541cb_volumes(
            self, **kw):
        """
        To get a fake detail storage_connectivity_group
        """
        return (200, {}, {
            "volumes": [
                {
                    "status": "available",
                    "display_name": "abcabc",
                    "attachments": [],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T07:22:20.729677",
                    "display_description": "None",
                    "volume_type": "shared_v7000_1-default",
                    "snapshot_id": "None",
                    "source_volid": "None",
                    "metadata": {},
                    "id": "ab41ee79-0f84-4f0d-976e-0aa122c8b89d",
                    "size": 1
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "103c1f3a-c2b2-4b90-80f8-cc2dd756b636",
                            "id": "2eab9958-16e1-4559-b3e6-e723360a4f27",
                            "volume_id":
                            "2eab9958-16e1-4559-b3e6-e723360a4f27"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:33:06.272849",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "103c1f3a-c2b2-4b90-80f8-cc2dd756b636",
                        "is_boot_volume": "True"
                    },
                    "id": "2eab9958",
                    "size": 4
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "6a81591c-1671-43d1-b8c2-e0eb09cdab84",
                            "id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf",
                            "volume_id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:32:30.922320",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "6a81591c-1671-43d1-b8c2-e0eb09cdab84",
                        "is_boot_volume": "True"
                    },
                    "id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf",
                    "size": 4
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "57625362-279c-4e02-bc9c-c6035904b2f1",
                            "id": "ff681131-9eab-4723-8261-6a80f8e3518d",
                            "volume_id": "ff681131-9eab-4723-8261-6a80f8e3518d"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:32:03.243339",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "57625362-279c-4e02-bc9c-c6035904b2f1",
                        "is_boot_volume": "True"
                    },
                    "id": "ff681131-9eab-4723-8261-6a80f8e3518d",
                    "size": 4
                }
                ]
        })

    def get_storage_connectivity_groups_sdfb541cb_volume_types(
            self, **kw):
        """
        To get a fake detail storage_connectivity_group
        """
        return (200, {}, {
            "volume-types": [
                {
                    "extra_specs": {
                        "drivers:storage_pool": "P-NGP01-pool",
                        "capabilities:volume_backend_name": "shared_v7000_1",
                        "drivers:rsize": "-1"
                    },
                    "name": "shared_v7000_1-default",
                    "id": "6627888e-9f59-4996-8c22-5d528c3273f0"
                },
                {
                    "extra_specs": {},
                    "name": "dm-crypt",
                    "id": "a3ae95f6-4aab-4446-b1d2-0fc2f60a89bb"
                },
                {
                    "extra_specs": {},
                    "name": "LUKS",
                    "id": "291f81a2-591b-4164-b2b2-829abc935573"
                }
                ]
        })

    def get_storage_connectivity_groups_f4b541cb_volumes(
            self, **kw):
        """
        To get a fake detail storage_connectivity_group
        """
        return (200, {}, {
            "volumes": [
                {
                    "status": "available",
                    "display_name": "abcabc",
                    "attachments": [],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T07:22:20.729677",
                    "display_description": "None",
                    "volume_type": "shared_v7000_1-default",
                    "snapshot_id": "None",
                    "source_volid": "None",
                    "metadata": {},
                    "id": "ab41ee79-0f84-4f0d-976e-0aa122c8b89d",
                    "size": 1
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "103c1f3a-c2b2-4b90-80f8-cc2dd756b636",
                            "id": "2eab9958-16e1-4559-b3e6-e723360a4f27",
                            "volume_id":
                            "2eab9958-16e1-4559-b3e6-e723360a4f27"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:33:06.272849",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "103c1f3a-c2b2-4b90-80f8-cc2dd756b636",
                        "is_boot_volume": "True"
                    },
                    "id": "2eab9958",
                    "size": 4
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "6a81591c-1671-43d1-b8c2-e0eb09cdab84",
                            "id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf",
                            "volume_id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:32:30.922320",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "6a81591c-1671-43d1-b8c2-e0eb09cdab84",
                        "is_boot_volume": "True"
                    },
                    "id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf",
                    "size": 4
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "57625362-279c-4e02-bc9c-c6035904b2f1",
                            "id": "ff681131-9eab-4723-8261-6a80f8e3518d",
                            "volume_id": "ff681131-9eab-4723-8261-6a80f8e3518d"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:32:03.243339",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "57625362-279c-4e02-bc9c-c6035904b2f1",
                        "is_boot_volume": "True"
                    },
                    "id": "ff681131-9eab-4723-8261-6a80f8e3518d",
                    "size": 4
                }
                ]
        })

    def get_storage_connectivity_groups_f4b541cb_volume_types(
            self, **kw):
        """
        To get a fake detail storage_connectivity_group
        """
        return (200, {}, {
            "volume-types": [
                {
                    "extra_specs": {
                        "drivers:storage_pool": "P-NGP01-pool",
                        "capabilities:volume_backend_name": "shared_v7000_1",
                        "drivers:rsize": "-1"
                    },
                    "name": "shared_v7000_1-default",
                    "id": "6627888e-9f59-4996-8c22-5d528c3273f0"
                },
                {
                    "extra_specs": {},
                    "name": "dm-crypt",
                    "id": "a3ae95f6-4aab-4446-b1d2-0fc2f60a89bb"
                },
                {
                    "extra_specs": {},
                    "name": "LUKS",
                    "id": "291f81a2-591b-4164-b2b2-829abc935573"
                }
                ]
        })

    def get_storage_connectivity_groups(self, **kw):
        """
        To return a fake storage_connectivity_groups
        """
        return (200, {}, {"storage_connectivity_groups": [
                {
                    "display_name": "Auto-SCG for Registered SAN",
                    "id": "f4b541cb"
                },
                {
                    "display_name": "SCG sample",
                    "id": "sdfb541cb"
                }
                ]})

    def get_storage_connectivity_groups_detail(self, **kw):
        """
        To return a fake detail storage_connectivity_groups
        """
        return (200, {}, {"storage_connectivity_groups": [
            {
                "auto_add_vios": True,
                "fc_storage_access": True,
                "display_name": "Auto-SCG for Registered SAN",
                "host_list": [
                    {
                        "name": "ngp01_02_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F715A",
                                "id": "ngp01_02_vios_1##1"
                            }
                        ]
                    },
                    {
                        "name": "ngp01_03_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F76CA",
                                "id": "ngp01_03_vios_1##1"
                            }
                        ]
                    }
                ],
                "created_at": "2013-08-23 14:56:11.787465",
                "enabled": True,
                "auto_defined": True,
                "id": "f4b541cb"
                },
            {
                "auto_add_vios": True,
                "fc_storage_access": True,
                "display_name": "SCG Sample",
                "host_list": [
                    {
                        "name": "ngp01_02_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F715A",
                                "id": "ngp01_02_vios_1##1"
                            }
                        ]
                    },
                    {
                        "name": "ngp01_03_vios_1",
                        "vios_list": [
                            {
                                "lpar_id": 1,
                                "name": "10-F76CA",
                                "id": "ngp01_03_vios_1##1"
                            }
                        ]
                    }
                ],
                "created_at": "2013-08-23 14:56:11.787465",
                "enabled": True,
                "auto_defined": True,
                "id": "sdfb541cb"
            }
        ]})


class PVCFakeCinderClient(cinderfakes.FakeClient):

    """
        This PVCFakeClient class extends the current cinder FakeClient,
        and pvccinderclient.CinderClient.
        aiming to set the self client variable to PVCFakeHTTPClient
    """

    def __init__(self, *args, **kwargs):
        cinderfakes.FakeClient.__init__(self, *args, **kwargs)
        self.client = PVCFakeCinderHTTPClient(**kwargs)


class PVCFakeCinderHTTPClient(cinderfakes.FakeHTTPClient):

    """
        This PVCFakeHTTPClient class extends the current cinder FakeHTTPClient.
        For all the HTTP requests in this class, it returns a fake json data
        as specified beforehand instead of requesting to a real environment.
    """

    def __init__(self, **kwargs):
        cinderfakes.FakeHTTPClient.__init__(self, **kwargs)

    #
    # Volumes related
    #
    def get_volumes_2eab9958(self, **kw):
        r = {'volume': self.get_volumes_detail()[2]['volumes'][0]}
        return (200, {}, r)

    def get_volumes_detail(self, **kw):
        """
        Override the parent method to a powerVC specified volume data.
        """
        return (200, {}, {
            "volumes": [
                {
                    "status": "available",
                    "display_name": "abcabc",
                    "attachments": [],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T07:22:20.729677",
                    "display_description": "None",
                    "volume_type": "shared_v7000_1-default",
                    "snapshot_id": "None",
                    "source_volid": "None",
                    "metadata": {},
                    "id": "ab41ee79-0f84-4f0d-976e-0aa122c8b89d",
                    "size": 1
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "103c1f3a-c2b2-4b90-80f8-cc2dd756b636",
                            "id": "2eab9958-16e1-4559-b3e6-e723360a4f27",
                            "volume_id":
                            "2eab9958-16e1-4559-b3e6-e723360a4f27"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:33:06.272849",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "103c1f3a-c2b2-4b90-80f8-cc2dd756b636",
                        "is_boot_volume": "True"
                    },
                    "id": "2eab9958",
                    "size": 4
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "6a81591c-1671-43d1-b8c2-e0eb09cdab84",
                            "id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf",
                            "volume_id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:32:30.922320",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "6a81591c-1671-43d1-b8c2-e0eb09cdab84",
                        "is_boot_volume": "True"
                    },
                    "id": "6c21891a-ce09-4701-98d7-1c8d0c6872cf",
                    "size": 4
                },
                {
                    "status": "in-use",
                    "display_name": "",
                    "attachments": [
                        {
                            "host_name": "None",
                            "device": "/dev/sda",
                            "server_id":
                            "57625362-279c-4e02-bc9c-c6035904b2f1",
                            "id": "ff681131-9eab-4723-8261-6a80f8e3518d",
                            "volume_id": "ff681131-9eab-4723-8261-6a80f8e3518d"
                        }
                    ],
                    "availability_zone": "nova",
                    "bootable": False,
                    "created_at": "2013-08-30T03:32:03.243339",
                    "os-vol-tenant-attr:tenant_id":
                    "2ec48b8ec30f4328bf95b8a5ad147c4b",
                    "display_description": "",
                    "os-vol-host-attr:host": "shared_v7000_1",
                    "health_status": {
                        "health_value": "OK"
                    },
                    "volume_type": "None",
                    "snapshot_id": "None",
                    "source_volid": "5f7c7d0d-b4e1-4ebc-80d4-4f1e8734f7e5",
                    "metadata": {
                        "instance_uuid":
                        "57625362-279c-4e02-bc9c-c6035904b2f1",
                        "is_boot_volume": "True"
                    },
                    "id": "ff681131-9eab-4723-8261-6a80f8e3518d",
                    "size": 4
                }
                ]
        })

    def post_volumes_pvcvolume_action(self, body, **kw):
        """
            Add this method to handle powerVC volume post actions
            Here is the same logic as OpenStack one for example.
        """
        _body = None
        resp = 202
        assert len(list(body.keys())) == 1
        action = list(body.keys())[0]
        if action == 'os-attach':
            assert sorted(list(body[action])) == ['instance_uuid',
                                                  'mode',
                                                  'mountpoint']
        elif action == 'os-detach':
            assert body[action] is None
        elif action == 'os-reserve':
            assert body[action] is None
        elif action == 'os-unreserve':
            assert body[action] is None
        elif action == 'os-initialize_connection':
            assert list(body[action].keys()) == ['connector']
            return (202, {}, {'connection_info': 'foos'})
        elif action == 'os-terminate_connection':
            assert list(body[action].keys()) == ['connector']
        elif action == 'os-begin_detaching':
            assert body[action] is None
        elif action == 'os-roll_detaching':
            assert body[action] is None
        elif action == 'os-reset_status':
            assert 'status' in body[action]
        else:
            raise AssertionError("Unexpected action: %s" % action)
        return (resp, {}, _body)

    #
    # volume type related
    #
    def get_types(self, **kw):
        return (200, {}, {
            "volume_types": [
                {
                    "extra_specs": {
                        "drivers:storage_pool": "P-NGP01-pool",
                        "capabilities:volume_backend_name": "shared_v7000_1",
                        "drivers:rsize": "-1"
                    },
                    "name": "shared_v7000_1-default",
                    "id": "6627888e-9f59-4996-8c22-5d528c3273f0"
                },
                {
                    "extra_specs": {},
                    "name": "dm-crypt",
                    "id": "a3ae95f6-4aab-4446-b1d2-0fc2f60a89bb"
                },
                {
                    "extra_specs": {},
                    "name": "LUKS",
                    "id": "291f81a2-591b-4164-b2b2-829abc935573"
                }
                ]
        })

    def get_storage_providers_2(self, **kw):
        """
        To get a fake detail storage_provider which id is 2
        """
        return (200, {}, {"storage_provider":
                          {
                              "backend_type": "svc",
                              "volume_count": "null",
                              "service": {
                                  "host_display_name": "shared_v7000_1",
                                  "host": "shared_v7000_1",
                                  "id": 4
                              },
                              "backend_id": "00000200A0204C30",
                              "health_status": {
                                  "health_value": "OK"
                              },
                              "free_capacity_gb": 873.5,
                              "total_capacity_gb": 1115.5,
                              "storage_hostname": "shared_v7000_1",
                              "id": 2,
                              "backend_state": "running"
                          }})

    def get_storage_providers_detail(self, **kw):
        """
        To return a fake detail storage_providers
        """
        return (200, {}, {"storage_providers": [
            {
                "backend_type": "svc",
                "volume_count": "null",
                "service": {
                    "host_display_name": "shared_v7000_1",
                    "host": "shared_v7000_1",
                    "id": 4
                },
                "backend_id": "00000200A0204C30",
                "health_status": {
                    "health_value": "OK"
                },
                "free_capacity_gb": 873.5,
                "total_capacity_gb": 1115.5,
                "storage_hostname": "shared_v7000_1",
                "id": 2,
                "backend_state": "running",
                "storage_type": "fc"
                },
            {
                "backend_type": "fc",
                "volume_count": "null",
                "service": {
                    "host_display_name": "shared_v7000_1",
                    "host": "shared_v7000_1",
                    "id": 4
                },
                "backend_id": "00000200A0204C31",
                "health_status": {
                    "health_value": "OK"
                },
                "free_capacity_gb": 73.5,
                "total_capacity_gb": 115.5,
                "storage_hostname": "shared_v7000_2",
                "id": 3,
                "backend_state": "running",
                "storage_type": "fc"
            }
        ]})


class FakeUtils(pvc_utils.Utils):

    def __init__(self):
        self._novaclient = None
        self._cinderclient = None
        self.scg_cache = None


class UtilsFakeTest(utils.TestCase):

    """
    Testcases for utils.py in this class reads the storage connectivity
    group, storage provider, storage template and volume from fake data.
    All the cases in this class should be run successfully.
    """

    def setUp(self):
        super(UtilsFakeTest, self).setUp()
        config.parse_power_config(['/etc/powervc/powervc.conf'], 'cinder')
        self.utils = FakeUtils()
        # get nova_client
        nova_fakeclient = PVCFakeNovaClient('r', 'p', 's',
                                            'http://localhost:5000/')
        # delegate to nova extension class
        nova_client = delegate.new_composite_deletgate(
            [ext_nova.Client(nova_fakeclient), nova_fakeclient])

        # get cinder client
        cinder_fakeclient = PVCFakeCinderClient('r', 'p')
        # delegate to nova extension class
        cinder_client = delegate.new_composite_deletgate(
            [ext_cinder.Client(cinder_fakeclient), cinder_fakeclient])

        self.utils._novaclient = nova_client
        self.utils._cinderclient = cinder_client
        self.utils.scg_cache = SCGCache(nova_client)

        self.scg_id_list = ['sdfb541cb',
                            'f4b541cb']
        self.scg_name_list = ['Auto-SCG for Registered SAN',
                              'SCG Sample']

    def test_get_multi_scg_accessible_storage_providers_1(self):
        accessible_storage_providers = \
            self.utils.get_multi_scg_accessible_storage_providers(
                scg_uuid_list=self.scg_id_list,
                scg_name_list=None)
        self.assertEqual([provider.storage_hostname
                          for provider in accessible_storage_providers],
                         ['shared_v7000_1', 'shared_v7000_2'])

    def test_get_multi_scg_accessible_storage_providers_2(self):
        accessible_storage_providers = \
            self.utils.get_multi_scg_accessible_storage_providers(
                scg_uuid_list=None,
                scg_name_list=self.scg_name_list)
        self.assertEqual([provider.id
                          for provider in accessible_storage_providers],
                         [2, 3])

    def test_get_scg_accessible_storage_providers_1(self):
        accessible_storage_providers = \
            self.utils.get_scg_accessible_storage_providers(
                "f4b541cb")
        self.assertEqual(accessible_storage_providers[0].storage_hostname,
                         "shared_v7000_1")

    def test_get_scg_accessible_storage_providers_2(self):
        """
        Test when scg not specified
        """
        accessible_storage_providers = \
            self.utils.get_scg_accessible_storage_providers()
        self.assertEqual(accessible_storage_providers[0].storage_hostname,
                         "shared_v7000_1")

    def test_get_multi_scg_accessible_storage_templates_1(self):
        accessible_storage_templates = \
            self.utils.get_multi_scg_accessible_storage_templates(
                scg_uuid_list=self.scg_id_list,
                scg_name_list=None)
        # Shoud return the storage template which in the accessible
        # storage providers
        self.assertEqual([st.name for st in accessible_storage_templates],
                         ['dm-crypt', 'LUKS', 'shared_v7000_1-default'])

    def test_get_multi_scg_accessible_storage_templates_2(self):
        accessible_storage_templates = \
            self.utils.get_multi_scg_accessible_storage_templates(
                scg_uuid_list=None,
                scg_name_list=self.scg_name_list)
        # Shoud return the storage template which in the accessible
        # storage providers
        self.assertEqual([st.name for st in accessible_storage_templates],
                         ['dm-crypt', 'LUKS', 'shared_v7000_1-default'])

    def test_get_scg_accessible_storage_templates_1(self):
        accessible_storage_templates = \
            self.utils.get_scg_accessible_storage_templates(
                "f4b541cb")
        # Shoud return the storage template which in the accessible
        # storage providers
        self.assertEqual(accessible_storage_templates[0].name,
                         "shared_v7000_1-default")

    def test_get_multi_scg_accessible_volumes_1(self):
        scg_accessible_volumes = \
            self.utils.get_multi_scg_accessible_volumes(
                scg_uuid_list=self.scg_id_list,
                scg_name_list=None)
        # Shoud return the volume which in the accessible
        # storage templates
        self.assertEqual([volume.id for volume in scg_accessible_volumes],
                         ["ab41ee79-0f84-4f0d-976e-0aa122c8b89d"])

    def test_get_scg_accessible_volumes_1(self):
        scg_accessible_volumes = \
            self.utils.get_scg_accessible_volumes(
                "f4b541cb")
        # Shoud return the volume which in the accessible
        # storage templates
        self.assertEqual(scg_accessible_volumes[0].id,
                         "ab41ee79-0f84-4f0d-976e-0aa122c8b89d")

    def test_get_multi_scg_accessible_volumes_2(self):
        scg_accessible_volumes = \
            self.utils.get_multi_scg_accessible_volumes(
                scg_uuid_list=None,
                scg_name_list=self.scg_name_list)
        # Shoud return the volume which in the accessible
        # storage templates
        self.assertEqual([volume.id for volume in scg_accessible_volumes],
                         ["ab41ee79-0f84-4f0d-976e-0aa122c8b89d"])

    def test_get_scg_accessible_volumes_2(self):
        scg_accessible_volumes = \
            self.utils.get_scg_accessible_volumes(
                scgName="Auto-SCG for Registered SAN")
        # Shoud return the volume which in the accessible
        # storage templates
        self.assertEqual(scg_accessible_volumes[0].id,
                         "ab41ee79-0f84-4f0d-976e-0aa122c8b89d")

    def test_get_scg_cache(self):
        new_scg = self.utils.get_scg_cache(self.utils._novaclient)
        self.assertNotEqual(new_scg, self.utils.scg_cache)

    def test_get_all_scgs(self):
        scg_list = self.utils.get_all_scgs()
        self.assertEqual([scg.id for scg in scg_list],
                         self.scg_id_list)

    def test_get_our_scg_list(self):
        from powervc.common import config as cg
        cg.CONF['powervc'].storage_connectivity_group = self.scg_name_list
        scg_list = self.utils.get_our_scg_list()
        self.assertIsNotNone(scg_list)

    def test_validate_scgs(self):
        from powervc.common import config as cg
        cg.CONF['powervc'].storage_connectivity_group = self.scg_name_list
        ret = self.utils.validate_scgs()
        self.assertTrue(ret)

    def test_get_scg_by_scgName_1(self):
        scg = self.utils.get_scg_by_scgName("Auto-SCG for Registered SAN")
        self.assertIsNotNone(scg)

    def test_get_scg_id_by_scgName_1(self):
        scg_id = self.utils.\
            get_scg_id_by_scgName("Auto-SCG for Registered SAN")
        self.assertEqual(scg_id, "f4b541cb")

    def test_get_scg_id_by_scgName_2(self):
        scg_id = self.utils.\
            get_scg_id_by_scgName("Auto-SCG for Registered SAN")
        self.assertIsNotNone(scg_id)

    def test_get_scg_id_by_scgName_3(self):
        scg_id = self.utils.\
            get_scg_id_by_scgName("NON-Auto-SCG for Registered SAN")
        self.assertEqual(scg_id, "")

    def test_get_scg_accessible_storage_servers_1(self):
        servers = self.utils.get_scg_accessible_servers()
        self.assertIsNotNone(servers)

    def test_get_scg_accessible_storage_servers_2(self):
        servers = self.utils.get_scg_accessible_servers(
            scgName="Auto-SCG for Registered SAN")
        self.assertIsNotNone(servers)

    def compare_to_expected(self, expected, hyper):
        for key, value in expected.items():
            self.assertEqual(getattr(hyper, key), value)

    def test_get_image_scgs(self):
        self.utils._novaclient = mock.MagicMock()
        self.utils.get_image_scgs('imageUUID')
        self.utils._novaclient.storage_connectivity_groups.\
            list_for_image.assert_called_with('imageUUID', False)

        scgs = self.utils.get_image_scgs(None)
        self.assertEqual(scgs, [])

    def test_get_scg_image_ids(self):
        self.utils._novaclient = mock.MagicMock()
        self.utils.get_scg_image_ids('scgUUID')
        self.utils._novaclient.scg_images.\
            list_ids.assert_called_with('scgUUID')
        imgs = self.utils.get_image_scgs(None)
        self.assertEqual(imgs, [])

    def test_get_local_staging_project_id(self):
        class Tenant(object):
            def __init__(self, name, tid):
                self.name = name
                self.id = tid

        self.utils._localkeystoneclient = mock.MagicMock()
        self.utils._localkeystoneclient.tenants.list.return_value = \
            [Tenant('fake_tenant_name1', 1), Tenant('fake_tenant_name2', 2)]
        from powervc.common import config as cg
        cg.CONF.powervc.staging_project_name = 'fake_tenant_name1'
        ret_id = self.utils.get_local_staging_project_id()
        self.assertEqual(ret_id, 1)

        cg.CONF.powervc.staging_project_name = 'no_tenant_name'
        from powervc.common.exception import StagingProjectNotFound
        self.assertRaises(StagingProjectNotFound,
                          self.utils.get_local_staging_project_id)

    def test_get_local_staging_user_id(self):
        class User(object):
            def __init__(self, name, tid):
                self.name = name
                self.id = tid

        self.utils._localkeystoneclient = mock.MagicMock()
        self.utils._localkeystoneclient.users.list.return_value = \
            [User('fake_user_name1', 1), User('fake_user_name2', 2)]
        from powervc.common import config as cg
        cg.CONF.powervc.staging_user = 'fake_user_name1'
        ret_id = self.utils.get_local_staging_user_id()
        self.assertEqual(ret_id, 1)

        cg.CONF.powervc.staging_user = 'no_user_name'
        from powervc.common.exception import StagingUserNotFound
        self.assertRaises(StagingUserNotFound,
                          self.utils.get_local_staging_user_id)

    def test_multi_thread_scgcache(self):
        # Launch one thousand one tasks to test the scg cache.
        class FakeScg(object):
            def __init__(self, scgid, name):
                self.id = scgid
                self.display_name = name

        def fake_get_resource():
            eventlet.greenthread.sleep(1)
            data1 = {}
            for i in range(1001):
                data1[FakeScg(str(i), 'scg' + str(i))] = 'scg' + str(i)
            return data1

        self.utils.scg_cache._get_resources = fake_get_resource

        def cache_task(key):
            scg1 = self.utils.scg_cache.by_id(key)
            self.assertEqual('scg' + key, scg1.display_name)
            scg2 = self.utils.scg_cache.by_name('scg' + key)
            self.assertEqual(key, scg2.id)
            print eventlet.greenthread.getcurrent

        pool = eventlet.GreenPool()
        pool.imap(cache_task, [str(i) for i in xrange(1001)])

    def test_filter_out_available_scgs(self):
        class FakeScg(object):
            def __init__(self, scgid, name):
                self.id = scgid
                self.display_name = name

        available_powervc_scgs = \
            {FakeScg('sdfb541cb', 'Auto-SCG for Registered SAN'),
             FakeScg('f4b541cb', 'SCG Sample')}
        from powervc.common import config as cg
        cg.CONF.powervc.storage_connectivity_group = ['SCG Sample']
        scg_to_use_list = \
            self.utils.filter_out_available_scgs(available_powervc_scgs)
        self.assertEqual(len(scg_to_use_list), 1)
        for scg in scg_to_use_list:
            self.assertEqual(scg.id, 'f4b541cb')

    def test_get_hypervisor_by_name(self):
        class FakeHypervisor(object):
            def __init__(self, hypervisorid, service, hypervisor_hostname):
                self.id = hypervisorid
                self.service = service
                self.hypervisor_hostname = hypervisor_hostname
        hypervisor_lists = {FakeHypervisor('1234',
                                           {'id': 1, 'host': 'compute1'},
                                           'hyper1'),
                            FakeHypervisor('5678',
                                           {'id': 2, 'host': 'compute2'},
                                           'hyper2')}
        self.utils._novaclient.hypervisors = hypervisor_lists
        test_hypervisor = self.utils.get_hypervisor_by_name('compute1')
        self.assertEqual(test_hypervisor.service['host'], 'compute1')


class FakeDriver(object):
    def set_data(self, data):
        self._data = data

    def cache_volume_data(self):
        return self._data


class VolumeCacheTest(testtools.TestCase):
    def setUp(self):
        super(VolumeCacheTest, self).setUp()
        self._driver = FakeDriver()

    def tearDown(self):
        super(VolumeCacheTest, self).tearDown()

    def test_get_resources(self):
        self._driver.set_data(None)
        volume_cache = VolumeCache(self._driver)
        self.assertEqual(None, volume_cache._get_resources())

        data1 = {'p000': 'l000'}
        self._driver.set_data(data1)
        volume_cache = VolumeCache(self._driver)
        self.assertEqual(data1, volume_cache._get_resources())

    def test_get_by_id(self):
        data1 = {'p000': 'l000'}
        self._driver.set_data(data1)
        volume_cache = VolumeCache(self._driver)
        self.assertEqual('l000', volume_cache.get_by_id('p000'))
        self.assertIsNone(volume_cache.get_by_id('p0001'))
        self.assertNotEquals('l001', volume_cache.get_by_id('p000'))

    def test_set_by_id(self):
        data1 = {'p000': 'l000'}
        self._driver.set_data(data1)
        volume_cache = VolumeCache(self._driver, 10000000)
        self.assertEqual('l000', volume_cache.get_by_id('p000'))
        volume_cache.set_by_id('p001', 'l001')
        self.assertEqual('l001', volume_cache.get_by_id('p001'))
        self.assertEqual('l000', volume_cache.get_by_id('p000'))

    def test_multi_thread(self):
        # Launch one thousand one tasks to test the cache.
        data1 = {}
        for i in range(1001):
            data1[str(i)] = 'value' + str(i)
        self._driver.set_data(data1)
        volume_cache = VolumeCache(self._driver, 10000000)

        def cache_task(key):
            str1 = volume_cache.get_by_id(key)
            self.assertEqual('value' + key, str1)
            volume_cache.set_by_id('country', 'china')
            str2 = volume_cache.get_by_id('country')
            self.assertEqual('china', str2)
            return "%s-%s, %s" % (key, str1, str2)

        pool = eventlet.GreenPool()
        i = 0
        for rtn in pool.imap(cache_task, data1.keys()):
            print "Got return from ", str(i), ': ', rtn
            i += 1
