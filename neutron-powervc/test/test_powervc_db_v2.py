COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import unittest
import mox
from sqlalchemy.orm.session import Session as session
from powervc.neutron.db.powervc_db_v2 import PowerVCAgentDB
from powervc.neutron.db import powervc_models_v2 as model
from sqlalchemy.engine.base import Transaction as transaction
from test.fake_powervc_network import FakePowerVCNetwork
from test.fake_os_network import FakeOSNetwork
from powervc.neutron.common import utils
from powervc.neutron.db.powervc_models_v2 import PowerVCMapping
from sqlalchemy.orm import Query as query


"""
    The class TestPowerVCNeutronDB is used to implement
    the UT test of the methods in the class PowerVCAgentDB
"""


class TestPowerVCNeutronDB(unittest.TestCase):

    def setUp(self):
        """
            This method is used to initialize the UT environment
        """

        # Initialize the FakePowerVCNetwork instance
        self.fakePowerVCNetwork = FakePowerVCNetwork()

        # Initialize the FakeOSNetwork instance
        self.fakeOSNetwork = FakeOSNetwork()

        # Initialize the PowerVCMapping instance
        async_key = utils.gen_network_sync_key(
            self.fakePowerVCNetwork.powerNetInstance)
        self.powerVCMapping = PowerVCMapping(
            obj_type="Network", sync_key=async_key)
        self.powerVCMapping.local_id = self.fakeOSNetwork.\
            fakeOSNetworkInstance['id']
        self.powerVCMapping.pvc_id = self.fakePowerVCNetwork.\
            powerNetInstance['id']
        self.powerVCMapping.status = "Active"
        self.powerVCMapping.id = None
        # Initialize the PowerVCAgentDB instance

        def __init__(self, session):
            self.session = session

        PowerVCAgentDB.__init__ = __init__
        self.powervcagentdb = PowerVCAgentDB(session)

        # Initialize the MOX instance
        self.aMox = mox.Mox()

    def tearDown(self):
        pass

    def test_create_object(self):
        """
            Test the method def _create_object(self, obj_type, sync_key,
            local_id=None, pvc_id=None)
        """

        obj_type = "Network"
        sync_key = utils.gen_network_sync_key(
            self.fakePowerVCNetwork.powerNetInstance)
        local_id = self.fakeOSNetwork.fakeOSNetworkInstance['id']
        pvc_id = self.fakePowerVCNetwork.powerNetInstance['id']

        inputPowerVCMObj = model.PowerVCMapping(obj_type, sync_key)

        self.aMox.StubOutWithMock(session, 'begin')
        session.begin(subtransactions=True).AndReturn(transaction(None, None))

        self.aMox.StubOutWithMock(model, 'PowerVCMapping')
        model.PowerVCMapping(obj_type, sync_key).AndReturn(inputPowerVCMObj)

        self.aMox.StubOutWithMock(session, 'add')
        session.add(inputPowerVCMObj).AndReturn("")

        self.aMox.ReplayAll()

        self.powervcagentdb._create_object(
            obj_type, sync_key, update_data=None,
            local_id=local_id, pvc_id=pvc_id)

        self.aMox.VerifyAll()

        self.assertEqual(
            self.powerVCMapping.local_id, inputPowerVCMObj.local_id)
        self.assertEqual(self.powerVCMapping.pvc_id, inputPowerVCMObj.pvc_id)
        self.assertEqual(self.powerVCMapping.status, inputPowerVCMObj.status)
        self.aMox.UnsetStubs()

    def test_delete_existing_object(self):
        """
            Test the method _delete_object(self, obj) when the object exists
            Test scenario:
            When the data is in the database, the delete operation should
            complete successfully
        """

        self.aMox.StubOutWithMock(session, 'query')
        session.query(model.PowerVCMapping).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'filter_by')
        query.filter_by(id=self.powerVCMapping['id']).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'one')
        query.one().AndReturn(self.powerVCMapping)

        self.aMox.StubOutWithMock(session, 'begin')
        session.begin(subtransactions=True).AndReturn(transaction(None, None))

        self.aMox.StubOutWithMock(session, 'delete')
        returnValue = session.delete(self.powerVCMapping).AndReturn(True)

        self.aMox.ReplayAll()

        self.powervcagentdb._delete_object(self.powerVCMapping)

        self.aMox.VerifyAll()

        self.assertEqual(returnValue, True)

        self.aMox.UnsetStubs()

    def test_get_objects_with_status(self):
        """Test the method def _get_objects(self, obj_type, status)
           Test scenario:
           Get the object when the status is not None
        """

        self.aMox.StubOutWithMock(session, 'query')
        session.query(model.PowerVCMapping).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'filter_by')
        query.filter_by(obj_type=self.powerVCMapping.obj_type,
                        status=self.powerVCMapping.status).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'all')
        query.all().AndReturn(self.powerVCMapping)

        self.aMox.ReplayAll()
        returnValue = self.powervcagentdb._get_objects(
            obj_type=self.powerVCMapping.obj_type,
            status=self.powerVCMapping.status)
        self.aMox.VerifyAll()
        self.assertEqual(returnValue, self.powerVCMapping)

        self.aMox.UnsetStubs()

    def test_get_object(self):
        """
            Test the method _get_object() using a sync key
            Test scenario:
            Get the object with sync_key
        """

        obj_type = self.powerVCMapping.obj_type
        sync_key = self.powerVCMapping.sync_key

        self.aMox.StubOutWithMock(session, 'query')
        session.query(model.PowerVCMapping).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'filter_by')
        query.filter_by(
            obj_type=obj_type, sync_key=sync_key).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'one')
        query.one().AndReturn(self.powerVCMapping)

        self.aMox.ReplayAll()
        returnValue = self.powervcagentdb._get_object(
            obj_type=obj_type, sync_key=sync_key)
        self.aMox.VerifyAll()
        self.assertEqual(returnValue, self.powerVCMapping)
        self.aMox.UnsetStubs()

    def test_set_object_pvc_id(self):
        """
            Test the method _set_object_pvc_id(self, obj, pvc_id)
            Test scenario:
            Set the pvc_id of the specified object when local_id is none
        """

        obj_id = self.powerVCMapping.id
        self.powerVCMapping.pvc_id = None
        self.powerVCMapping.local_id = None
        self.powerVCMapping.status = None

        self.aMox.StubOutWithMock(session, 'query')
        session.query(model.PowerVCMapping).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'filter_by')
        query.filter_by(id=obj_id).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'one')
        query.one().AndReturn(self.powerVCMapping)

        self.aMox.StubOutWithMock(session, 'merge')
        session.merge(self.powerVCMapping).AndReturn("")

        self.aMox.ReplayAll()
        self.powervcagentdb._set_object_pvc_id(self.powerVCMapping, 'test')
        self.aMox.VerifyAll()
        self.assertEqual(self.powerVCMapping.status, 'Creating')
        self.assertEqual(self.powerVCMapping.pvc_id, 'test')
        self.aMox.UnsetStubs()

    def test_set_object_local_id(self):
        """
            Test the method _set_object_local_id(self, obj, local_id)
            Test scenario:
            Set the local_id of the specified object when the pvc_id is none
        """

        obj_id = self.powerVCMapping.id
        self.powerVCMapping.pvc_id = None
        self.powerVCMapping.local_id = None
        self.powerVCMapping.status = None

        self.aMox.StubOutWithMock(session, 'query')
        session.query(model.PowerVCMapping).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'filter_by')
        query.filter_by(id=obj_id).AndReturn(query)

        self.aMox.StubOutWithMock(query, 'one')
        query.one().AndReturn(self.powerVCMapping)

        self.aMox.StubOutWithMock(session, 'merge')
        session.merge(self.powerVCMapping).AndReturn("")

        self.aMox.ReplayAll()
        self.powervcagentdb._set_object_local_id(self.powerVCMapping, 'test')
        self.aMox.VerifyAll()
        self.assertEqual(self.powerVCMapping.status, 'Creating')
        self.assertEqual(self.powerVCMapping.local_id, 'test')
        self.aMox.UnsetStubs()
