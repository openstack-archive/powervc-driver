# Copyright 2013 IBM Corp.
from cinder.openstack.common import gettextutils
gettextutils.install('cinder')
import unittest
import mox
from powervc.volume.manager.manager import PowerVCCinderManager
from powervc.volume.driver.service import PowerVCService

fake_volume_type = {'id': '',
                    'name': 'fake_volume_type'
                    }


fake_volume = {'display_name': 'fake_volume',
               'display_description': 'This is a fake volume',
               'volume_type_id': '',
               'status': '',
               'host': 'powervc',
               'size': 1,
               'availability_zone': 'nova',
               'bootable': 0,
               'snapshot_id': '',
               'source_volid': '',
               'metadata': {},
               'project_id': 'admin',
               'user_id': 'admin',
               'attached_host': 'fake_attached_host',
               'mountpoint': '',
               'instance_uuid': '',
               'attach_status': ''}

fake_message = {'payload': {'volume_id': '', 'display_name': ''}}

fake_context = {}


class FakeDBVolume():
    def __init__(self):
        pass


class FakeVolume():
    def __init__(self):
        pass

    def __dict__(self):
        return None

    # Comment it because of unused and could not pass flake8
    # __dict__ = fake_volume


class FakePowerVCService(PowerVCService):
    def __init__(self):
        pass

fake_db_volume = FakeDBVolume()


class Test(unittest.TestCase):
    def setUp(self):
        self.moxer = mox.Mox()

        def __init__(self):
            pass

        PowerVCCinderManager.__init__ = __init__
        self.manager = PowerVCCinderManager()

    def tearDown(self):
        pass

    def test_handle_powervc_volume_create_not_create(self):
        self.manager._service = self.moxer.CreateMock(PowerVCService)
        self.moxer.StubOutWithMock(self.manager,
                                   '_get_local_volume_by_pvc_id')
        self.moxer.StubOutWithMock(self.manager._service,
                                   'get_volume_by_id')
        self.moxer.StubOutWithMock(self.manager, '_insert_pvc_volume')

        pvc_id = ''
        self.manager._get_local_volume_by_pvc_id(fake_context, pvc_id)\
                    .AndReturn(fake_db_volume)

        self.moxer.ReplayAll()

        self.manager._handle_powervc_volume_create(fake_context, fake_message)

        self.moxer.UnsetStubs()
        self.moxer.VerifyAll()

    def test_handle_powervc_volume_create_create(self):
        self.manager._service = self.moxer.CreateMock(PowerVCService)
        self.moxer.StubOutWithMock(self.manager,
                                   '_get_local_volume_by_pvc_id')
        self.moxer.StubOutWithMock(self.manager._service,
                                   'get_volume_by_id')
        self.moxer.StubOutWithMock(self.manager, '_insert_pvc_volume')

        pvc_id = ''
        volume_id = ''
        fake_volume_instance = FakeVolume()
        self.manager._get_local_volume_by_pvc_id(fake_context, pvc_id)\
                    .AndReturn(None)
        self.manager._insert_pvc_volume(fake_context, {}).AndReturn(None)
        self.manager._service.get_volume_by_id(volume_id)\
                    .AndReturn(fake_volume_instance)
        self.manager._service.get_volumes()\
                    .AndReturn([fake_volume_instance])

        self.moxer.ReplayAll()

        self.manager._handle_powervc_volume_create(fake_context, fake_message)

        self.moxer.UnsetStubs()
        self.moxer.VerifyAll()

if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
