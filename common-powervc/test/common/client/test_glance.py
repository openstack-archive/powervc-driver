# Copyright 2013 IBM Corp.
import unittest
import mox
from mock import MagicMock
import glanceclient.v1.images as imagesV1
import glanceclient.v1.image_members as membersV1

from glanceclient.openstack.common import gettextutils
gettextutils.install('common-glance-client-ut')

import powervc.common.utils as common_utils

utils = common_utils.import_relative_module('glanceclient', 'tests.utils')
test_images = common_utils.import_relative_module('glanceclient',
                                                  'tests.v1.test_images')
test_image_members = common_utils.import_relative_module(
    'glanceclient',
    'tests.v1.test_image_members')

from powervc.common.client.extensions.glance import Client as PVCGlanceClient


class FakeGlanceClient(object):

    """
        Fake client to populate the pvcglanceclient.Client
    """

    def __init__(self, images, members):
        self.images = images
        self.image_members = members
        self.image_tags = MagicMock()


class TestPVCGlanceClient(unittest.TestCase):

    def setUp(self):
        # prepare the fake api
        images_api = utils.FakeAPI(test_images.fixtures)  # @UndefinedVariable
        images_manager = imagesV1.ImageManager(images_api)

        members_api = utils.FakeAPI(  # @UndefinedVariable
            test_image_members.fixtures
        )
        members_manager = membersV1.ImageMemberManager(members_api)

        # create mock object
        self.moxer = mox.Mox()
        client = self.moxer.CreateMockAnything()
        self.pvc_gc = PVCGlanceClient(client)

        # append the fake api to mock object
        self.pvc_gc.client.images = images_manager
        self.pvc_gc.client.image_members = members_manager
        self.pvc_gc.client.image_tags = MagicMock()

    def test_listImages(self):
        self.moxer.ReplayAll()
        images = self.pvc_gc.listImages()
        self.moxer.VerifyAll()
        self.assertEqual(images[0].id, 'a')
        self.assertEqual(images[0].name, 'image-1')
        self.assertEqual(images[1].id, 'b')
        self.assertEqual(images[1].name, 'image-2')

    def test_getImage(self):
        self.moxer.ReplayAll()
        image = self.pvc_gc.getImage('1')
        self.moxer.VerifyAll()
        self.assertEqual(image.id, '1')
        self.assertEqual(image.name, 'image-1')

    def test_deleteImage(self):
        self.moxer.ReplayAll()
        self.pvc_gc.deleteImage('1')
        expect = [
            ('DELETE', '/v1/images/1', {}, None),
        ]
        self.moxer.VerifyAll()
        self.assertEqual(self.pvc_gc.
                         client.
                         images.
                         api.calls,
                         expect)

    def test_listImageMembers(self):
        self.moxer.ReplayAll()
        image_id = '1'
        image_members = self.pvc_gc.listImageMembers(image_id)
        self.moxer.VerifyAll()
        self.assertEqual(image_members[0].image_id, '1')
        self.assertEqual(image_members[0].member_id, '1')

    def test_deleteImageMember(self):
        self.moxer.ReplayAll()
        image_id = '1'
        member_id = '1'
        self.pvc_gc.deleteImageMember(image_id, member_id)
        expect = [
            ('DELETE',
             '/v1/images/{image}/members/{mem}'.
             format(image='1',
                    mem='1'),
             {},
             None)]
        self.moxer.VerifyAll()
        self.assertEqual(self.pvc_gc.client.image_members.
                         api.calls,
                         expect)

    def test_getImageFile(self):
        self.pvc_gc.client.images.data = MagicMock(return_value='FILE')
        ret = self.pvc_gc.getImageFile('image_id')
        self.pvc_gc.client.images.data.assert_called_once_with('image_id')
        self.assertEqual(ret, 'FILE')

    def test_updateImage(self):
        self.pvc_gc.client.images.update = MagicMock(return_value='updated')
        ret = self.pvc_gc.updateImage('image_id')
        self.pvc_gc.client.images.update.assert_called_once_with('image_id')
        self.assertEqual(ret, 'updated')

    def test_updateImageMember(self):
        self.pvc_gc.client.image_members.update =\
            MagicMock(return_value='member updated')
        ret = self.pvc_gc.updateImageMember('image_id',
                                            'member_id',
                                            'member_status')
        self.pvc_gc.client.image_members.update.\
            assert_called_once_with('image_id',
                                    'member_id',
                                    'member_status')
        self.assertEqual(ret, 'member updated')

    def test_createImageMember(self):
        self.pvc_gc.client.image_members.create =\
            MagicMock(return_value='member created')
        ret = self.pvc_gc.createImageMember('image_id', 'member_id')
        self.pvc_gc.client.image_members.create.\
            assert_called_once_with('image_id',
                                    'member_id')
        self.assertEqual(ret, 'member created')

    def test_updateImageTag(self):
        self.pvc_gc.client.image_tags.update =\
            MagicMock(return_value='tag updated')
        self.pvc_gc.client_version = 2
        ret = self.pvc_gc.updateImageTag('image_id', 'tag_value')
        self.pvc_gc.client.image_tags.update.\
            assert_called_once_with('image_id',
                                    'tag_value')
        self.assertEqual(ret, 'tag updated')

    def test_deleteImageTag(self):
        self.pvc_gc.client.image_tags.delete =\
            MagicMock(return_value='tag deleted')
        self.pvc_gc.client_version = 2
        ret = self.pvc_gc.deleteImageTag('image_id', 'tag_value')
        self.pvc_gc.client.image_tags.delete.\
            assert_called_once_with('image_id',
                                    'tag_value')
        self.assertEqual(ret, 'tag deleted')

    def tearDown(self):
        pass


if __name__ == "__main__":
    unittest.main()
