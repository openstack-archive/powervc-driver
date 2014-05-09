# Copyright 2013 IBM Corp.

import json
import socket
import urllib2
import urlparse


def is_ipv4_address(ip_or_host):
    """Determines if a netloc is an IPv4 address.

    :param ip_or_host: the host/ip to check
    """
    try:
        socket.inet_aton(ip_or_host)
        return True
    except:
        return False


def hostname_url(url):
    """Converts the URL into its FQHN form.
    This requires DNS to be setup on the OS or the hosts table
    to be updated.

   :param url: the url to convert to FQHN form
    """
    frags = urlparse.urlsplit(url)
    if is_ipv4_address(frags.hostname) is True:
        return url
    try:
        fqhn, alist, ip = socket.gethostbyaddr(frags.hostname)
    except:
        # likely no DNS configured, return inital url
        return url
    port_str = ''
    if frags.port is not None:
        port_str = ':' + str(frags.port)
    return frags.scheme + '://' + fqhn + port_str + frags.path


def extract_url_segment(url, needles):
    """searches the url segments for the 1st occurence
    of an element in the list of search keys.

    :param url: the url or uri to search
    :param needles: the keys to search for
    """
    for seg in reversed(url.split('/')):
        if seg in needles:
            return seg
    return None


class JSONRESTClient(object):
    """a simple json rest client
    """
    def __init__(self, token):
        self.token = token

    def get(self, url):
        """perform a http GET on the url

        :param url: the url to GET
        """
        return self._rest_call(url)

    def post(self, url, json_body):
        """perform a http POST on the url

        :param url: the url to POST
        :param json_body: the body to POST
        """
        return self._rest_call(url, 'POST', json_body)

    def put(self, url, json_body):
        """perform a http PUT on the url

        :param url: the url to PUT
        :param json_body: the body to PUT
        """
        return self._rest_call(url, 'PUT', json_body)

    def delete(self, url):
        """perform an http DELETE on the url

        :param url: the url to DELETE
        """
        return self._rest_call(url, 'DELETE')

    def _rest_call(self, url, method='GET', json_body=None):
        request = urllib2.Request(url)
        request.add_header('Content-Type', 'application/json;charset=utf8')
        request.add_header('Accept', 'application/json')
        request.add_header('User-Agent', 'python-client')
        if self.token:
            request.add_header('X-Auth-Token', self.token)
        if json_body:
            request.add_data(json.dumps(json_body))
        request.get_method = lambda: method
        try:
            response = urllib2.urlopen(request)
        except urllib2.HTTPError as e:
            if e.code == 300:
                return json.loads(e.read())
            raise e
        return json.loads(response.read())
