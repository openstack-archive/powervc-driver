# Copyright 2013 IBM Corp.

import logging
import re
import urlparse

import powervc.common.client.delegate as delegate
from glanceclient.openstack.common import importutils
from powervc.common.constants import SERVICE_TYPES as SERVICE_TYPES
from powervc.common import netutils

LOG = logging.getLogger(__name__)


class AbstractService(object):
    """a stub over a service endpoint which permits consumers
    to create openstack python clients directly from this object.
    """
    def __init__(self, svc_type, version, url, base_args, keystone):
        self.svc_type = svc_type
        self.version = version
        self.url = url
        self.base_args = base_args.copy()
        self.keystone = keystone
        self.base_name = SERVICE_TYPES[svc_type].to_codename()
        self.client_version = version = version.replace('.', '_')
        self.clazz = self._lookup_client()
        self.extension = self._lookup_extension()
        self.management_url = url

    def _extend(self, client, client_extension=None, *extension_args):
        if self.extension is None and client_extension is None:
            return client
        delegates = []
        if client_extension is not None:
            delegates.append(client_extension(client, *extension_args))
        if self.extension is not None:
            delegates.append(self.extension(client, *extension_args))
        delegates.append(client)
        # extend the base client using a mixin type delegate
        return delegate.new_composite_deletgate(delegates)

    def _patch(self, client):
        try:
            # if applicable patch the client
            module = (importutils.
                      import_module("powervc.common.client.patch.%s" %
                                    (self.base_name)))
            module.patch_client(self, client)
        except ImportError:
            pass
        return client

    def _lookup_client(self):
        return importutils.import_class("%sclient.%s.client.Client" %
                                       (self.base_name,
                                        self.get_client_version()))

    def _lookup_extension(self):
        try:
            return (importutils.
                    import_class("powervc.common.client.extensions.%s.Client" %
                                 (self.base_name)))
        except ImportError:
            return None
        return None

    def _chomp_version(self, version):
        match = re.search('(v[0-9])[_]*[0-9]*', version, re.IGNORECASE)
        if match:
            version = match.group(1)
        return version

    def _init_std_client(self):
        region_name = self.base_args.get('region_name', None)
        return self._patch(self.clazz(self.base_args['username'],
                                      self.base_args['password'],
                                      self.base_args['tenant_name'],
                                      self.base_args['auth_url'],
                                      self.base_args['insecure'],
                                      region_name=region_name,
                                      cacert=self.base_args['cacert']))

    def new_client(self, client_extension=None, *extension_args):
        """build and return a new python client for this service

        :param client_extension: the optional subclass of
        powervc.common.client.extensions.base to extend the python client with.
        :param extension_args: optional arguments to pass to the client
        extension when it is created.
        """
        return self._extend(self._init_std_client(), client_extension,
                            *extension_args)

    def get_client_version(self):
        """returns the version of the client for this service
        """
        return self.client_version


class KeystoneService(AbstractService):
    """wrappers keystone service endpoint
    """
    def __init__(self, *kargs):
        super(KeystoneService, self).__init__(*kargs)

    def new_client(self, client_extension=None, *extension_args):
        return self._extend(self.clazz(**self.base_args), client_extension,
                            *extension_args)

    def get_client_version(self):
        if self.client_version == 'v3_0':
            return 'v3'
        return self.client_version


class CinderService(AbstractService):
    """wrappers cinder service endpoint
    """
    def __init__(self, *kargs):
        super(CinderService, self).__init__(*kargs)

    def get_client_version(self):
        return self._chomp_version(self.client_version)


class NovaService(AbstractService):
    """wrappers nova service endpoint
    """
    def __init__(self, *kargs):
        super(NovaService, self).__init__(*kargs)

    def get_client_version(self):
        if re.search('v2', self.client_version) is not None:
            return 'v1_1'
        return self.client_version


class GlanceService(AbstractService):
    """wrappers glance service endpoint
    """
    def __init__(self, *kargs):
        super(GlanceService, self).__init__(*kargs)

    def new_client(self, client_extension=None, *extension_args):
        url = self.url
        if not url.endswith('/'):
            url += '/'
        return (self.
                _extend(self.
                        _patch(self.clazz(url, token=self.keystone.auth_token,
                                          insecure=self.base_args['insecure'],
                                          cacert=self.base_args['cacert'])),
                        client_extension, *extension_args))

    def get_client_version(self):
        return self._chomp_version(self.client_version)


class NeutronService(AbstractService):
    """wrappers neutron service endpoint
    """
    def __init__(self, *kargs):
        super(NeutronService, self).__init__(*kargs)

    def new_client(self, client_extension=None, *extension_args):
        region_name = self.base_args.get('region_name', None)
        return self._extend(self._patch(self.clazz(
                            username=self.base_args['username'],
                            tenant_name=self.base_args['tenant_name'],
                            password=self.base_args['password'],
                            auth_url=self.base_args['auth_url'],
                            endpoint_url=self.management_url,
                            insecure=self.base_args['insecure'],
                            region_name=region_name,
                            token=self.keystone.auth_token,
                            ca_cert=self.base_args['cacert'])),
                            client_extension, *extension_args)

    def get_client_version(self):
        if self.client_version.startswith('v1'):
            return 'v2_0'
        return self.client_version


class ClientServiceCatalog(object):
    """provides a simple catalog of openstack services
    for a single host and permits consumers to query
    those services based on service types, versions
    as well as create new python clients from the service
    directly.
    """
    def __init__(self, base_client_opts, keystone):
        self.base_opts = base_client_opts
        self.keystone = keystone

        # validate authN
        self.token = self.keystone.auth_token

        self.host = urlparse.urlsplit(self.base_opts['auth_url']).hostname
        self.endpoints = {}
        self.blacklist = [str(SERVICE_TYPES.s3), str(SERVICE_TYPES.ec2),
                          str(SERVICE_TYPES.ttv)]

        self._discover_services()

    def new_client(self, svc_type, client_extension=None, *extension_args):
        """creates a new python client for the given service type
        using the most recent version of the service in the catalog.

        :param svc_type: the service type to create a client for
        :param client_extension: the optional extension to decorate
        the base client with
        :param extension_args: optional arguments to pass to the client
        extension when it is created.
        """
        service_versions = self.get_services(svc_type)
        if service_versions:
            return service_versions[0].new_client(client_extension,
                                                  *extension_args)
        return None

    def get_services(self, svc_type, version_filter=None):
        """queries this catalogs services based on service type
        and version filter.

        :param svc_type: the type of service to query.
        :param version_filter: a filter string to indicate the
        service version the caller wants. if None the highest
        version of the service is returned.
        """
        if svc_type not in self.endpoints:
            return None
        versions = self.endpoints[svc_type]
        # Here we need test version_filter is None or empty, use 'if not'.
        if not version_filter:
            return versions[max(versions, key=str)]
        for version in versions.keys():
            if version.find(version_filter) > -1:
                return versions[version]
        # >> fix bug/1358215, timing issue between openstack service endpoints
        # becoming active and powervc-driver's client initialization of those.
        #
        # 1. get_client() call with version_filter might runs into the 'None'
        # client error mentioned in the bug, which means *currently* only
        # glance sync is affected. When no version filtered, we do a rediscover
        # for the svc_type.
        # 2. get_client() call without version_filter or new_client() call just
        # choose the latest avaiable version service, so no 'None' client
        # error, although the chosen version might not be the real *latest* but
        # the default hardcoded 'v1' version, due to the timing issue mentioned
        # in the bug. For the latter case, unless there is an observation/noti-
        # fication mechanism or poll mechanism for service versions update,
        # based on current design, there is no perfect solution as far as I can
        # imagine.
        # TODO(design): re-consider for #2
        else:
            # I don't think a lock is needed here. Only glance sync service use
            # specified version apis and might run into this and starup_sync
            # won't pass until the specified versions are ready. So there
            # shouldn't be concurrent accesses to self.endpoints[svc_type] with
            # svc_type='image'.
            LOG.info(_("rediscover service for type:" + svc_type))
            self._rediscover_service(svc_type)
            versions = self.endpoints[svc_type]
            for version in versions.keys():
                if version.find(version_filter) > -1:
                    return versions[version]
        # << fix bug/1358215
        return None

    def get_versions(self, svc_type):
        """return a list of the versions for the given service type

        :param svc_type: the type of service to query
        """
        if svc_type not in self.endpoints:
            return None
        return self.endpoints[svc_type].keys()

    def get_version(self, svc_type, version_filter=None):
        """query a service to determine if a given version exists.

        :param svc_type: the service type to query.
        :param version_filter: a string to search for in the version.
        if None the most recent version of the service type is returned.
        """
        if svc_type not in self.endpoints:
            return None
        for version in self.endpoints[svc_type].keys():
            if not version_filter or version.find(version_filter) > -1:
                return version
        return None

    def get_service_types(self):
        """returns a list of all service types in this catalog.
        """
        return self.endpoints.keys()

    def get_token(self):
        """returns a keystone token for the host this catalog
        belongs to.
        """
        return self.keystone.auth_token

    def get_client(self, svc_type, version_filter=None, client_extension=None,
                   *extension_args):
        """creates a new python cient for the given service type
        and version.

        :param svc_type: the service type to create a client for.
        :param version_filter: a string to search for in the version
        the caller wants. if None the most recent version is used.
        :param client_extension: the optional class to extend
        the client with
        """
        services = self.get_services(svc_type, version_filter)
        if not services:
            return None
        return services[0].new_client(client_extension, *extension_args)

    def _parse_link_href(self, links):
        hrefs = []
        for link_meta in links:
            if link_meta['rel'] == 'self':
                href = self._filter_host(link_meta['href'])
                hrefs.append(href)
        return hrefs

    def _filter_host(self, loc):
        # endpoint urls from base api query will often
        # return localhost in the url; resolve those
        return loc.replace('localhost',
                           self.host).replace('127.0.0.1',
                                              self.host).replace('0.0.0.0',
                                                                 self.host)

    def _parse_version_meta(self, ver, ver_map={}):
        ver_map[ver['id']] = self._parse_link_href(ver['links'])
        return ver_map

    def _parse_version(self, response_json, url):
        if response_json is not None:
            if 'version' in response_json:
                return {response_json['version']['id']:
                        [self._filter_host(url)]}
            elif 'versions' in response_json:
                services = {}
                versions = response_json['versions']
                if 'values' in versions:
                    versions = versions['values']
                for version_meta in versions:
                    if 'status' in version_meta and \
                            version_meta['status'] == 'CURRENT':
                        ver = version_meta['id']
                        if not ver in services:
                            services[ver] = []
                        services[ver].append(self._filter_host(url))
                return services
        return None

    def _parse_version_from_url(self, url):
        for seg in reversed(url.split('/')):
            match = re.search('^(v[0-9][.]?[0-9]?$)', seg, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _build_wrappered_services(self, version_map, svc_type):
        services = {}
        for version in version_map.keys():
            wrappers = []
            for s_url in version_map[version]:
                if svc_type == (str(SERVICE_TYPES.compute) or
                                svc_type == str(SERVICE_TYPES.computev3)):
                    wrappers.append(NovaService(svc_type, version,
                                                s_url, self.base_opts,
                                                self.keystone))
                elif svc_type == str(SERVICE_TYPES.image):
                    wrappers.append(GlanceService(svc_type, version,
                                                  s_url, self.base_opts,
                                                  self.keystone))
                elif svc_type == str(SERVICE_TYPES.identity):
                    # keystone is a special case as the auth url given
                    # in the base opts may not match the auth url from
                    # the catalog
                    keystone_opts = self.base_opts.copy()
                    keystone_opts['auth_url'] = s_url
                    wrappers.append(KeystoneService(svc_type, version,
                                                    s_url, keystone_opts,
                                                    self.keystone))
                elif svc_type == str(SERVICE_TYPES.volume):
                    wrappers.append(CinderService(svc_type, version,
                                                  s_url, self.base_opts,
                                                  self.keystone))
                elif svc_type == str(SERVICE_TYPES.network):
                    wrappers.append(NeutronService(svc_type, version,
                                                   s_url, self.base_opts,
                                                   self.keystone))
            services[version] = wrappers
        return services

    def _query_endpoint(self, url):
        # query the endpoint to get version info
        client = netutils.JSONRESTClient(self.get_token())
        urldata = urlparse.urlsplit(url)
        host = urldata.scheme + '://' + urldata.netloc
        segments = filter(lambda x: x != '', urldata.path.split('/'))
        if not segments:
            segments = ['']
        # chomp uri until we find base of endpoint
        for segment in segments[:] or ['']:
            endpoint_url = "%s/%s/" % (host, '/'.join(segments))
            segments.pop()
            response = None
            try:
                response = client.get(endpoint_url)
            except:
                continue
            versions = self._parse_version(response, url)
            if versions is not None:
                return versions
        return {'v1': [url]}

    def _build_endpoint_services(self, url, svc_type):
        # try to parse from the url
        ver = self._parse_version_from_url(url)
        if ver is not None:
            return self._build_wrappered_services({ver: [url]}, svc_type)
        versions = self._query_endpoint(url)
        return self._build_wrappered_services(versions, svc_type)

    def _normalize_catalog_entry(self, entry):
        for key in entry.keys():
            if re.search('url', key, re.IGNORECASE):
                entry[key] = self._filter_host(entry[key])
            if self.keystone.version == 'v2.0':
                # keystone v2.0 entries differ from v3; normalize
                entry['url'] = entry['publicURL']
        return entry

    def _discover_services(self):
        public_eps = (self.keystone.
                      service_catalog.get_endpoints(endpoint_type='publicURL'))
        self.endpoints = {}
        for svc_type in public_eps.keys():
            if svc_type in self.blacklist:
                continue
            for entry in public_eps[svc_type]:
                entry = self._normalize_catalog_entry(entry)
                self.endpoints[svc_type] = \
                    self._build_endpoint_services(entry['url'], svc_type)

    # >> fix bug/1358215, timing issue between openstack service endpoints
    # becoming active and powervc-driver's client initialization of those.
    def _rediscover_service(self, svc_type):
        public_eps = (self.keystone.
                      service_catalog.get_endpoints(endpoint_type='publicURL'))
        for entry in public_eps[svc_type]:
            entry = self._normalize_catalog_entry(entry)
            self.endpoints[svc_type] = \
                self._build_endpoint_services(entry['url'], svc_type)
    # << fix bug/1358215
