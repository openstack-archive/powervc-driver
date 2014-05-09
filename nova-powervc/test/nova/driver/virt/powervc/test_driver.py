# Copyright 2014 IBM Corp.
import sys
import mock
import testtools
import threading
import os
from nova import exception
os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
from nova import test
from nova.openstack.common import jsonutils
from nova.compute import task_states
from nova.image import glance
from nova import db
from novaclient import exceptions
import unittest
from powervc import utils as powervc_utils
sys.modules['powervc.common.client'] = mock.MagicMock()
from mock import MagicMock
from powervc.nova.driver.virt.powervc.service import PowerVCService
from powervc.nova.driver.virt.powervc.driver import PowerVCDriver
from powervc.nova.driver.virt.powervc.driver import CONF as driver_conf
from powervc.nova.driver.virt.powervc import pvc_vm_states
from test.fake_pvc_instance import FakePVCInstance
from test.fake_os_instance import FakeOSInstance
from powervc.nova.driver.compute import constants
from nova.exception import MigrationPreCheckError as mpcError
from nova.exception import Invalid

pvcIns = FakePVCInstance()
hostname = '789523X_10421DB'


def _change_state(ins, status):
    ins.status = status


class FakeClient(object):
    def __init__(self):
        pass


class FakeHostStat(object):
    stat = dict()

    def __init__(self):
        self.stat['vcpus'] = 8.5
        self.stat['vcpus_used'] = 1
        self.stat['local_gb'] = 1024
        self.stat['local_gb_used'] = 1024 - 500
        self.stat['proc_units_reserved'] = 0
        self.stat['memory_mb'] = 1000
        self.stat['memory_mb_reserved'] = 0
        self.stat['memory_mb_used'] = 500
        self.stat['disk_available_least'] = 50
        self.stat['hypervisor_type'] = 'powervm'
        self.stat['hypervisor_version'] = 7
        self.stat['cpu_info'] = 'powervm'
        self.stat['hypervisor_hostname'] = hostname
        self.stat['supported_instances'] = \
            jsonutils.dumps(constants.POWERVC_SUPPORTED_INSTANCES)


class Server():
    def __init__(self, status):
        self.status = status
        self.id = '98765'
        self.metadata = dict()


class Volume():
    def __init__(self):
        self.metadata = dict()
        self.metadata['pvc:id'] = 'pvc_volume_id'


class Attachment():
    def __init__(self):
        self.volumeId = 'pvc_volume_id'


class PowerVCDriverTestCase(test.NoDBTestCase):

    def save_before_patch(self):
        self.pvcsvc_init_copy = PowerVCService.__init__
        self.pvcsvc_get_server_copy = PowerVCService._get_server
        self.pvcsvc_get_pvcserver_copy = PowerVCService._get_pvcserver
        self.pvcdrv_init_copy = PowerVCDriver.__init__

    def patch(self):
        PowerVCService.__init__ = MagicMock(return_value=None)
        PowerVCService._get_server = MagicMock(return_value=pvcIns)
        PowerVCService._get_pvcserver = MagicMock(return_value=pvcIns)
        PowerVCDriver.__init__ = MagicMock(return_value=None)

    def unpatch(self):
        PowerVCService.__init__ = self.pvcsvc_init_copy
        PowerVCService._get_server = self.pvcsvc_get_server_copy
        PowerVCService._get_pvcserver = self.pvcsvc_get_pvcserver_copy
        PowerVCDriver.__init__ = self.pvcdrv_init_copy

    def setUp(self):
        super(PowerVCDriverTestCase, self).setUp()
        self.save_before_patch()
        self.patch()
        self._driver = PowerVCDriver()
        self._driver._service = PowerVCService(FakeClient())
        self._driver._service.longrun_loop_interval = 1
        self._driver._service.longrun_initial_delay = 1
        self._driver._service._manager = MagicMock()
        self._driver._service._manager.get = \
            MagicMock(return_value=pvcIns)
        self._driver._service._validate_response = MagicMock()
        glance.get_default_image_service = MagicMock()
        self.pvc_id = 123456789
        self._driver.hostname = hostname
        pvcIns.__dict__["OS-EXT-SRV-ATTR:host"] = "source_host_name"

    def test_power_on_active_instance(self):
        # Test an already ACTIVE instance.
        pvcIns.status = pvc_vm_states.ACTIVE
        self._driver.power_on(None, pvcIns, None)
        self.assertEqual(pvc_vm_states.ACTIVE, pvcIns.status,
                         "Tested power on an ACTIVE instance.")

    def test_power_on_shutoff_instance(self):
        # Test an OFF instance"
        pvcIns.status = pvc_vm_states.SHUTOFF
        # Use a timer to change the status later.
        timer = threading.Timer(1, _change_state,
                                [pvcIns, pvc_vm_states.ACTIVE])
        timer.start()
        self._driver.power_on(None, pvcIns, None)
        timer.cancel()
        self.assertEqual(pvc_vm_states.ACTIVE, pvcIns.status,
                         "Tested power on a SHUTOFF instance.")

    def test_power_off_shutoff_instance(self):
        # Test an OFF instance.
        pvcIns.status = pvc_vm_states.SHUTOFF
        self._driver.power_off(pvcIns)
        self.assertEqual(pvc_vm_states.SHUTOFF, pvcIns.status,
                         "Tested power off an SHUTOFF instance.")

    def test_power_off_active_instance(self):
        # Test power off an active instance.
        pvcIns.status = pvc_vm_states.ACTIVE
        timer = threading.Timer(1, _change_state,
                                [pvcIns, pvc_vm_states.SHUTOFF])
        timer.start()
        self._driver.power_off(pvcIns)
        timer.cancel()
        self.assertEqual(pvc_vm_states.SHUTOFF, pvcIns.status,
                         "Tested power off an SHUTOFF instance.")

    def test_get_available_resource(self):
        fake_hypervisor = MagicMock()
        fake_hypervisor_info = FakeHostStat().stat
        fake_hypervisor._info = fake_hypervisor_info
        self._driver.get_hypervisor_by_hostname = \
            MagicMock(return_value=fake_hypervisor)
        stats = self._driver.get_available_resource(None)
        int_fake_vcpu = int(fake_hypervisor_info['vcpus'])
        self.assertEqual(stats['vcpus'], int_fake_vcpu)
        self.assertEqual(stats['local_gb'], fake_hypervisor_info['local_gb'])
        fake_local_gb_used = fake_hypervisor_info['local_gb_used']
        self.assertEqual(stats['local_gb_used'], fake_local_gb_used)
        self.assertEqual(stats['memory_mb'], fake_hypervisor_info['memory_mb'])
        fake_memory_mb_used = fake_hypervisor_info['memory_mb_used']
        self.assertEqual(stats['memory_mb_used'], fake_memory_mb_used)
        fake_hypervisor_type = fake_hypervisor_info['hypervisor_type']
        self.assertEqual(stats['hypervisor_type'], fake_hypervisor_type)
        fake_hypervisor_version = fake_hypervisor_info['hypervisor_version']
        self.assertEqual(stats['hypervisor_version'], fake_hypervisor_version)
        self.assertEqual(stats['hypervisor_hostname'], self._driver.hostname)
        self.assertEqual(stats['supported_instances'], jsonutils.dumps(
            constants.POWERVC_SUPPORTED_INSTANCES))

    def test_get_available_resource_memory_disc(self):
        fake_hypervisor = MagicMock()
        fake_hypervisor_info = FakeHostStat().stat
        fake_hypervisor._info = fake_hypervisor_info
        fake_hypervisor_info['proc_units_reserved'] = 3
        fake_hypervisor_info['memory_mb_reserved'] = 50
        self._driver.get_hypervisor_by_hostname = \
            MagicMock(return_value=fake_hypervisor)
        stats = self._driver.get_available_resource(None)
        fake_hypervisor._info = fake_hypervisor_info
        vcpu_expected = int(fake_hypervisor_info['vcpus'] -
                            fake_hypervisor_info['proc_units_reserved'])
        self.assertEqual(stats['vcpus'], vcpu_expected)
        memory_expected = int(fake_hypervisor_info['memory_mb'] -
                              fake_hypervisor_info['memory_mb_reserved'])
        self.assertEqual(stats['memory_mb'], memory_expected)

    def test_check_can_live_migrate_source(self):
        pass

    def test_check_can_live_migrate_destination_cleanup(self):
        pass

    def test_check_can_live_migrate_destination_no_instance(self):
        os_instance = FakeOSInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=None)
        cclmd = self._driver.check_can_live_migrate_destination
        dest_compute_info = FakeHostStat().stat
        self.assertRaises(mpcError, cclmd, None,
                          os_instance, None, dest_compute_info)

    def test_check_can_live_migrate_destination_invalid_state(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        cclmd = self._driver.check_can_live_migrate_destination
        dest_compute_info = FakeHostStat().stat
        service._is_live_migration_valid = MagicMock(return_value=False)
        self.assertRaises(mpcError, cclmd, None,
                          os_instance, None, dest_compute_info)

    def test_check_can_live_migrate_destination_block_migration(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        cclmd = self._driver.check_can_live_migrate_destination
        dest_compute_info = FakeHostStat().stat
        service._is_live_migration_valid = MagicMock(return_value=True)
        self.assertRaises(mpcError, cclmd, None,
                          os_instance, None,
                          dest_compute_info, block_migration=True)

    def test_check_can_live_migrate_destination_disc_over_commit(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        cclmd = self._driver.check_can_live_migrate_destination
        dest_compute_info = FakeHostStat().stat
        service._is_live_migration_valid = MagicMock(return_value=True)
        self.assertRaises(mpcError, cclmd, None,
                          os_instance, None,
                          dest_compute_info, disk_over_commit=True)

    def test__check_defer_placement(self):
        os_instance = FakeOSInstance()
        driver = self._driver
        os_instance.os_instance['metadata']['powervm:defer_placement'] = 'true'
        self.assertTrue(driver._check_defer_placement(os_instance))
        os_instance.os_instance['metadata']['powervm:defer_placement'] = \
            'false'
        self.assertFalse(driver._check_defer_placement(os_instance))
        #if the property is not presented
        del os_instance.os_instance['metadata']['powervm:defer_placement']
        self.assertFalse(driver._check_defer_placement(os_instance))

    def test_check_can_live_migrate_destination_defer_placement(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        cclmd = self._driver.check_can_live_migrate_destination
        dest_compute_info = FakeHostStat().stat
        service._is_live_migration_valid = MagicMock(return_value=True)
        os_instance.os_instance['metadata']['powervm:defer_placement'] = 'true'
        self.assertEquals(dest_compute_info, cclmd(None, os_instance, None,
                                                   dest_compute_info))
        os_instance.os_instance['metadata']['powervm:defer_placement'] = \
            'false'
        service.get_valid_destinations = MagicMock(return_value=[])
        self.assertRaises(Invalid, cclmd, None,
                          os_instance, None, dest_compute_info)
        service.get_valid_destinations = \
            MagicMock(return_value=[driver_conf.get('host')])
        self.assertEquals(dest_compute_info, cclmd(None, os_instance, None,
                                                   dest_compute_info))

    def test_live_migrate(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        dest_compute_info = FakeHostStat().stat
        os_instance.os_instance['metadata']['powervm:defer_placement'] = \
            'false'
        recover_method = MagicMock()
        post_method = MagicMock()

        def change_host(server):
            server.__dict__["OS-EXT-SRV-ATTR:host"] = "dest_host_name"
        timer = threading.Timer(1, change_host,
                                [pvcIns])
        timer.start()
        self._driver.live_migration(None, os_instance, dest_compute_info,
                                    post_method, recover_method)
        timer.cancel()
        post_method.assert_called_once_with(None, os_instance,
                                            dest_compute_info, False, None)

    def test_live_migrate_with_defer(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        dest_compute_info = FakeHostStat().stat
        os_instance.os_instance['metadata']['powervm:defer_placement'] = 'true'
        recover_method = MagicMock()
        post_method = MagicMock()

        def change_host(server):
            server.__dict__["OS-EXT-SRV-ATTR:host"] = "dest_host_name"
        timer = threading.Timer(1, change_host,
                                [pvcIns])
        timer.start()
        self._driver.live_migration(None, os_instance, dest_compute_info,
                                    post_method, recover_method)
        timer.cancel()
        post_method.assert_called_once_with(None, os_instance,
                                            None, False, None)

    def test_live_migrate_with_recover(self):
        os_instance = FakeOSInstance()
        pvc_instance = FakePVCInstance()
        service = self._driver._service
        service.get_instance = MagicMock(return_value=pvc_instance)
        dest_compute_info = FakeHostStat().stat
        os_instance.os_instance['metadata']['powervm:defer_placement'] = \
            'false'
        recover_method = MagicMock()
        post_method = MagicMock()
        service.live_migrate = MagicMock(side_effect=Exception("Error"))
        self.assertRaises(Exception, self._driver.live_migration,
                          None, os_instance, dest_compute_info,
                          post_method, recover_method)
        recover_method.assert_called_once_with(None, os_instance,
                                               dest_compute_info, False, None)

    def test_confirm_migration(self):
        pvc_driver = self._driver
        pvc_driver._service = MagicMock()
        pvc_driver._service.confirm_migration = MagicMock()
        migration = 0
        instance = 0
        network_info = 0
        pvc_driver.confirm_migration(migration, instance, network_info)
        pvc_driver._service.confirm_migration.assert_called_once_with(instance)

    def test_deatch_volumn(self):
        pvc_driver = self._driver
        pvc_driver._service._volumes = MagicMock()
        pvc_driver._service._volumes.delete_server_volume = MagicMock()
        pvc_driver._service._get_pvc_volume_id = MagicMock(return_value=1)
        pvc_driver._service.longrun_loop_interval = 0
        pvc_driver._service.longrun_initial_delay = 0
        pvc_driver._service.max_tries = 2
        #pvc_driver._service.
        connection_info = {"serial": 1}
        metadata = {"pvc_id": 1}
        instance = {"metadata": metadata}
        pvc_driver.detach_volume(connection_info, instance, None)
        PowerVCService._get_pvc_volume_id
        pvc_driver._service._get_pvc_volume_id.assert_called_once_with(1)
        pvc_driver._service._volumes.delete_server_volume.\
            assert_called_once_with(1, 1)

    def test_finish_migration(self):
        pvc_driver = self._driver
        pvc_driver.confirm_migration = MagicMock()
        pvc_driver.power_on = MagicMock()
        pvc_driver._service.resize_instance = MagicMock()
        pvc_driver._service.update_correct_host = MagicMock()
        context = 0
        migration = 0
        instance = 0
        disk_info = 0
        network_info = 0
        image_meta = 0
        resize_instance = True
        block_device_info = 0
        power_on = True
        pvc_driver.finish_migration(context, migration, instance,
                                    disk_info, network_info, image_meta,
                                    resize_instance, block_device_info,
                                    power_on)
        pvc_driver._service.resize_instance.assert_called_once_with(context,
                                                                    migration,
                                                                    instance,
                                                                    image_meta)
        pvc_driver.confirm_migration.assert_called_once_with(None,
                                                             instance, None)
        pvc_driver._service.update_correct_host(context, instance)
        pvc_driver.power_on.assert_called_once_with(context, instance,
                                                    network_info,
                                                    block_device_info)

    def test_snapshot(self):
        pvc_driver = self._driver
        pvc_driver._service.snapshot = MagicMock()
        context = MagicMock()
        instance = 1
        image_id = 1
        update_task_state = MagicMock()
        pvc_driver.snapshot(context, instance, image_id,
                            update_task_state)
        update_task_state.assert_any_call(
                            task_state=task_states.IMAGE_PENDING_UPLOAD)
        update_task_state.assert_any_call(
                            task_state=task_states.IMAGE_UPLOADING,
                            expected_state=task_states.IMAGE_PENDING_UPLOAD)

    def tearDown(self):
        super(PowerVCDriverTestCase, self).tearDown()
        self.unpatch()


class TestDriver(unittest.TestCase):
    def setUp(self):
        def init(self, pvc_client=None):
            pass
        PowerVCDriver.__init__ = init
        PowerVCService.__init__ = init
        self.powervc_driver = PowerVCDriver()
        self.powervc_driver.hypervisor_id = "fake_hypervisor_id_123456"
        self.powervc_driver._service = PowerVCService(None)
        self.powervc_driver._service._manager = mock.MagicMock()
        self.powervc_driver._service._volumes = mock.MagicMock()
        self.powervc_driver._service._cinderclient = mock.MagicMock()
        self.powervc_driver._service.longrun_loop_interval = 2
        self.powervc_driver._service.longrun_initial_delay = 3
        self.powervc_driver._service.max_tries = 3

    def test_spawn_success(self):
        context = None
        instance = self.fake_instance()
        image_meta = self.fake_image_meta()
        injected_files = None
        admin_password = None
        PowerVCDriver._check_defer_placement = \
            mock.MagicMock(return_value=False)
        #mock database operation
        db.flavor_get = mock.MagicMock()
        PowerVCDriver._get_pvc_network_info = mock.MagicMock()
        self.powervc_driver._service.validate_update_scg = mock.MagicMock()
        createdServer = Server(pvc_vm_states.BUILD)
        self.powervc_driver._service._manager.create = \
            mock.MagicMock(return_value=createdServer)
        createFinished = Server(pvc_vm_states.ACTIVE)
        self.powervc_driver._service._manager.get = \
            mock.MagicMock(return_value=createFinished)
        self.powervc_driver._service.\
            _update_local_instance_by_pvc_created_instance = \
            mock.MagicMock()
        self.powervc_driver._clean_vm_and_save_fault_message = \
            mock.MagicMock()
        metadata = dict()
        powervc_utils.fill_metadata_dict_by_pvc_instance = \
            mock.MagicMock(return_value=metadata)
        self.powervc_driver._service.\
            _update_local_instance_by_pvc_created_instance = \
            mock.MagicMock()
        resultServer = self.powervc_driver.spawn(context,
                                          instance,
                                          image_meta,
                                          injected_files,
                                          admin_password)
        self.assertEquals(createFinished,
                          resultServer,
                          'success')

    def test_spawn_instance_invalid_state_exception(self):
        context = None
        instance = self.fake_instance()
        image_meta = self.fake_image_meta()
        injected_files = None
        admin_password = None
        PowerVCDriver._check_defer_placement = \
            mock.MagicMock(return_value=False)
        #mock database operation
        db.flavor_get = mock.MagicMock()
        PowerVCDriver._get_pvc_network_info = mock.MagicMock()
        self.powervc_driver._service.validate_update_scg = \
            mock.MagicMock()
        createdServer = Server('ERROR')
        self.powervc_driver._service._manager.create = \
            mock.MagicMock(return_value=createdServer)
        createFinished = Server(pvc_vm_states.ACTIVE)
        self.powervc_driver._service._manager.get = \
            mock.MagicMock(return_value=createFinished)
        self.powervc_driver._service.\
            _update_local_instance_by_pvc_created_instance = \
            mock.MagicMock()
        self.powervc_driver._clean_vm_and_save_fault_message = \
            mock.MagicMock()
        metadata = dict()
        powervc_utils.fill_metadata_dict_by_pvc_instance = \
            mock.MagicMock(return_value=metadata)
        self.powervc_driver._service.\
            _update_local_instance_by_pvc_created_instance = \
            mock.MagicMock()
        self.assertRaises(exception.InstanceInvalidState,
                          self.powervc_driver.spawn,
                          context,
                          instance,
                          image_meta,
                          injected_files,
                          admin_password)

    def test_destroy_success(self):
        instance = self.fake_instance_for_destroy()
        context = None
        network_info = None
        self.powervc_driver._service._servers = mock.MagicMock()
        server = Server(pvc_vm_states.ACTIVE)
        self.powervc_driver._service.Server = \
            mock.MagicMock(return_value=server)
        manager_get_server_from_instance = \
            Server(pvc_vm_states.ACTIVE)
        manager_get_server_from_destroy_instance = \
            Server('DELETED')
        setattr(manager_get_server_from_destroy_instance,
                'OS-EXT-STS:task_state', None)
        self.powervc_driver._service._manager.get = \
            mock.MagicMock(
                    side_effect=[manager_get_server_from_instance,
                    manager_get_server_from_destroy_instance])
        self.powervc_driver._service._manager.delete = \
            mock.MagicMock()
        self.powervc_driver._service._validate_response = \
            mock.MagicMock()
        result = self.powervc_driver.destroy(context,
                                             instance, network_info)
        self.assertEqual(result, True, "delete success")

    def test_destroy_not_found_exception(self):
        instance = self.fake_instance_for_destroy()
        context = None
        network_info = None
        self.powervc_driver._service._servers = mock.MagicMock()
        server = Server(pvc_vm_states.ACTIVE)
        self.powervc_driver._service.Server = \
            mock.MagicMock(return_value=server)
        self.powervc_driver._service._manager.get = \
            mock.MagicMock(side_effect=exceptions.NotFound('404'))
        expr = self.powervc_driver.destroy(context,
                                           instance,
                                           network_info)
        self.assertTrue(expr, "faild")

    def test_destroy_instanceTerminationFailure_exception(self):
        instance = self.fake_instance_for_destroy()
        context = None
        network_info = None
        self.powervc_driver._service._servers = mock.MagicMock()
        server = Server(pvc_vm_states.ACTIVE)
        self.powervc_driver._service.Server = \
            mock.MagicMock(return_value=server)
        manager_get_server_from_instance = \
            Server(pvc_vm_states.ACTIVE)
        manager_get_server_from_destroy_instance = Server('ACTIVE')
        setattr(manager_get_server_from_destroy_instance,
                'OS-EXT-STS:task_state', 'active')
        self.powervc_driver._service._manager.get = \
            mock.MagicMock(
                side_effect=[manager_get_server_from_instance,
                            manager_get_server_from_destroy_instance])
        self.powervc_driver._service._manager.delete = mock.MagicMock()
        self.powervc_driver._service._validate_response = mock.MagicMock()
        self.assertRaises(exception.InstanceTerminationFailure,
                          self.powervc_driver.destroy,
                          context,
                          instance,
                          network_info)

    def fake_image_meta(self):
        image_meta = dict()
        image_meta['deleted'] = False
        image_meta['id'] = 'image_meta_id'
        properties = dict()
        properties['powervc_uuid'] = 'fake_pvc_uuid'
        image_meta['properties'] = properties
        return image_meta

    def fake_instance(self):
        instance = dict()
        instance['instance_type_id'] = 'fake_instace_type_id'
        instance['host'] = 'fake_host'
        instance['uuid'] = 'fake_uuid'
        instance['hostname'] = 'fake_host_name'
        meta = dict()
        meta[u'powervm:defer_placement'] = 'true'
        meta['pvc_id'] = 'fake_pvc_id'
        instance['metadata'] = meta
        return instance

    def fake_instance_for_destroy(self):
        instance = dict()
        instance['instance_type_id'] = 'fake_instace_type_id'
        instance['host'] = 'fake_host'
        instance['uuid'] = 'fake_uuid'
        instance['hostname'] = 'fake_host_name'
        meta = dict()
        meta['key'] = 'pvc_id'
        meta['value'] = 'pvc_key_value'
        instance['metadata'] = [meta]
        return instance


class TestGetInstance(testtools.TestCase):
    """This is the test fixture for PowerVCDriver.get_instance."""

    def setUp(self):
        """Prepare for this test fixture."""
        super(TestGetInstance, self).setUp()
        self.pvc_id = 123456789
        # save before monkey patch
        self.pvcdrv_init_copy = PowerVCDriver.__init__

    def test_get_instance_found(self):
        """When get instance find an instance."""
        pvc_svc = mock.MagicMock()
        pvc_svc.get_instance = mock.MagicMock(return_value="an instance")

        def pvc_drv_init_instance_found(self):
            """A fake init to replace PowerVCDriver.__init__."""
            self._service = pvc_svc

        # monkey patch
        PowerVCDriver.__init__ = pvc_drv_init_instance_found
        pvc_drv = PowerVCDriver()

        self.assertIsNotNone(pvc_drv.get_instance(self.pvc_id))

    def test_get_instance_not_found(self):
        """When get instance find nothing."""
        pvc_svc = mock.MagicMock()
        pvc_svc.get_instance = mock.MagicMock(side_effect=
                                              exceptions.NotFound(0))

        def pvc_drv_init_instance_not_found(self):
            """A fake init to replace PowerVCDriver.__init__."""
            self._service = pvc_svc

        # monkey patch
        PowerVCDriver.__init__ = pvc_drv_init_instance_not_found
        pvc_drv = PowerVCDriver()

        self.assertIsNone(pvc_drv.get_instance(self.pvc_id))

    def tearDown(self):
        """Clean work for this test fixture."""
        super(TestGetInstance, self).tearDown()
        # restore from monkey patch
        PowerVCDriver.__init__ = self.pvcdrv_init_copy


class TestGetInfo(testtools.TestCase):
    """This is the test fixture for PowerVCDriver.get_info."""

    def setUp(self):
        """Prepare for this test fixture."""
        super(TestGetInfo, self).setUp()
        # fake data
        self.os_instance = FakeOSInstance().os_instance
        self.pvc_instance = FakePVCInstance()

        # save before monkey patch
        pvcdrv_init_copy = PowerVCDriver.__init__
        # monkey patch
        PowerVCDriver.__init__ = mock.MagicMock(return_value=None)
        self.pvc_drv = PowerVCDriver()
        #restore from monkey patch, no need to wait until tearDown
        PowerVCDriver.__init__ = pvcdrv_init_copy

    def test_get_info_success(self):
        """When everything is fine in the main path."""
        self.pvc_drv.get_instance = mock.MagicMock(return_value=
                                                   self.pvc_instance)
        self.assertEqual(self.pvc_drv.get_info(self.os_instance),
                         {'state': 1,
                          'max_mem': 8192,
                          'mem': 2048,
                          'num_cpu': 2,
                          'cpu_time': 0
                          }
                         )

    def test_get_info_instance_not_found_0(self):
        """When any exception occurred during fetch PVC LPAR instance."""
        self.pvc_drv.get_instance = mock.MagicMock(side_effect=
                                                   exception.NotFound())
        self.assertRaises(exception.NotFound,
                          self.pvc_drv.get_info,
                          self.os_instance)

    def test_get_info_instance_not_found_1(self):
        """When no PVC LPAR instance found."""
        self.pvc_drv.get_instance = mock.MagicMock(return_value=None)
        self.assertRaises(exception.NotFound,
                          self.pvc_drv.get_info,
                          self.os_instance)
