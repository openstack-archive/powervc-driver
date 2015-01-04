# Copyright 2013 IBM Corp.

import powervc.common.client.extensions.base as base

from glanceclient.common import http
from glanceclient.common import utils
from glanceclient.v2 import image_members
from glanceclient.v2 import image_tags
from glanceclient.v2 import images
from glanceclient.v2 import schemas


class Extended_V2_Client(object):
    """
    Client for the Glance Images v2 API.

    :param dict client_info : The client info dict to init a glance v2 client
    """
    def __init__(self, client_info):
        endpoint = utils.strip_version(client_info['endpoint'])
        kwargs = {'cacert': client_info['cacert'],
                  'insecure': client_info['insecure'],
                  'token': client_info['token']}

        if isinstance(endpoint, tuple):
            endpoint = endpoint[0]
        self.http_client = http.HTTPClient(endpoint, **kwargs)
        self.schemas = schemas.Controller(self.http_client)
        self.images = images.Controller(self.http_client, self.schemas)
        self.image_tags = image_tags.Controller(self.http_client, self.schemas)
        self.image_members = image_members.Controller(self.http_client,
                                                      self.schemas)


class Client(base.ClientExtension):

    def __init__(self, client):
        super(Client, self).__init__(client)

    def listImages(self):
        return [image for image in self.client.images.list()]

    def getImage(self, image_id):
        return self.client.images.get(image_id)

    def getImageFile(self, image_id):
        return self.client.images.data(image_id)

    def deleteImage(self, image_id):
        return self.client.images.delete(image_id)

    def updateImage(self, image_id, **kwargs):
        return self.client.images.update(image_id, **kwargs)

    def listImageMembers(self, image_id):
        return [imageMember for imageMember in
                self.client.image_members.list(image_id)]

    def deleteImageMember(self, image_id, member_id):
        self.client.image_members.delete(image_id, member_id)

    def updateImageMember(self, image_id, member_id, member_status):
        return self.client.image_members.update(image_id, member_id,
                                                member_status)

    def createImageMember(self, image_id, member_id):
        return self.client.image_members.create(image_id, member_id)

    def updateImageTag(self, image_id, tag_value):
        if self.client_version == 2:
            return self.client.image_tags.update(image_id, tag_value)

    def deleteImageTag(self, image_id, tag_value):
        if self.client_version == 2:
            return self.client.image_tags.delete(image_id, tag_value)
