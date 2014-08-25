# Copyright 2013 IBM Corp.

import powervc.common.client.extensions.base as base


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
