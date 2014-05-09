# Copyright 2013 IBM Corp.

import warlock


def patch_client(service_wrapper, client):

    http_client = client
    if hasattr(client, 'http_client'):
        http_client = client.http_client

    org_http_request = http_client._http_request

    """
    Patch the _http_request method of glance client and inject
    a keystone managed token and management url. this allows us
    to ensure a valid token is maintained an also support keystone
    v3 apis.
    """
    def _patched_http_request(url, method, **kwargs):
        # patch glance HTTPClient to use our keystone for tokens
        # and support for non standard URLs
        if http_client.endpoint_path and\
                not http_client.endpoint_path.endswith('/'):
            http_client.endpoint_path += '/'
        http_client.auth_token = service_wrapper.keystone.auth_token
        if url.startswith('/'):
            url = url[1:]
        return org_http_request(url, method, **kwargs)

    http_client._http_request = _patched_http_request

    def _patched_raw_request(method, url, **kwargs):
        '''
        Patch the http raw_request method to fix a problem. If there is no
        image data set the content-type in the headers to application/json.
        Failure to do so can lead to errors during image updates and creates.
        '''
        kwargs.setdefault('headers', {})
        if 'body' in kwargs:
            if kwargs['body'] is None:
                kwargs['headers'].setdefault('Content-Type',
                                             'application/json')
            else:
                kwargs['headers'].setdefault('Content-Type',
                                             'application/octet-stream')
            if (hasattr(kwargs['body'], 'read')
                    and method.lower() in ('post', 'put')):
                # We use 'Transfer-Encoding: chunked' because
                # body size may not always be known in advance.
                kwargs['headers']['Transfer-Encoding'] = 'chunked'
        else:
            kwargs['headers'].setdefault('Content-Type',
                                         'application/json')
        return _patched_http_request(url, method, **kwargs)

    http_client.raw_request = _patched_raw_request

    """
    Patch v2 glanceclient controller for update image
    """
    ver = str(client).split('.')[1]
    if ver != 'v2':
        # if not v2 client, nothing else to do
        return

    org_image_controller = client.images

    def _patched_image_update(image_id, remove_props=None, **kwargs):
        """
        Update attributes of an image.

        This is patched to fix an issue. The Content-Type should reflect v2.1
        since that is the version of the patch schema that is used.

        :param image_id: ID of the image to modify.
        :param remove_props: List of property names to remove
        :param **kwargs: Image attribute names and their new values.
        """
        image = org_image_controller.get(image_id)
        for (key, value) in kwargs.items():
            try:
                setattr(image, key, value)
            except warlock.InvalidOperation as e:
                raise TypeError(unicode(e))

        if remove_props is not None:
            cur_props = image.keys()
            new_props = kwargs.keys()
            #NOTE(esheffield): Only remove props that currently exist on the
            # image and are NOT in the properties being updated / added
            props_to_remove = set(cur_props).intersection(
                set(remove_props).difference(new_props))

            for key in props_to_remove:
                delattr(image, key)

        url = '/v2/images/%s' % image_id
        hdrs = {'Content-Type': 'application/openstack-images-v2.1-json-patch'}
        http_client.raw_request('PATCH', url,
                                headers=hdrs,
                                body=image.patch)

        #NOTE(bcwaldon): calling image.patch doesn't clear the changes, so
        # we need to fetch the image again to get a clean history. This is
        # an obvious optimization for warlock
        return org_image_controller.get(image_id)

    org_image_controller.update = _patched_image_update
