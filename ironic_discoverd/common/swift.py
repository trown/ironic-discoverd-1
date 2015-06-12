# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Mostly copied from ironic/common/swift.py

import logging

from oslo_config import cfg
from swiftclient import client as swift_client
from swiftclient import exceptions as swift_exceptions

from ironic_discoverd.common.i18n import _
from ironic_discoverd import utils

CONF = cfg.CONF


LOG = logging.getLogger('ironic_inspector.common.swift')


SWIFT_OPTS = [
    cfg.IntOpt('max_retries',
               default=2,
               help='Maximum number of times to retry a Swift request, '
                    'before failing.'),
    cfg.IntOpt('delete_after',
               default=0,
               help='Number of seconds that the Swift object will last before '
                    'being deleted. (set to 0 to never delete the object).'),
    cfg.StrOpt('container',
               default='ironic-inspector',
               help='Default Swift container to use when creating objects.'),
    cfg.StrOpt('username',
               default='',
               help='User name for accessing Swift API.'),
    cfg.StrOpt('password',
               default='',
               help='Password for accessing Swift API.',
               secret=True),
    cfg.StrOpt('tenant_name',
               default='',
               help='Tenant name for accessing Swift API.'),
    cfg.StrOpt('os_auth_version',
               default='2',
               help='Keystone authentication API version'),
    cfg.StrOpt('os_auth_url',
               default='',
               help='Keystone authentication URL'),
]


def list_opts():
    return [
        ('swift', SWIFT_OPTS)
    ]

CONF.register_opts(SWIFT_OPTS, group='swift')


class SwiftAPI(object):
    """API for communicating with Swift."""

    def __init__(self,
                 user=CONF.swift.username,
                 tenant_name=CONF.swift.tenant_name,
                 key=CONF.swift.password,
                 auth_url=CONF.swift.os_auth_url,
                 auth_version=CONF.swift.os_auth_version):
        """Constructor for creating a SwiftAPI object.

        :param user: the name of the user for Swift account
        :param tenant_name: the name of the tenant for Swift account
        :param key: the 'password' or key to authenticate with
        :param auth_url: the url for authentication
        :param auth_version: the version of api to use for authentication
        """
        params = {'retries': CONF.swift.max_retries,
                  'user': user,
                  'tenant_name': tenant_name,
                  'key': key,
                  'authurl': auth_url,
                  'auth_version': auth_version}

        self.connection = swift_client.Connection(**params)

    def create_object(self, object, data, container='ironic-inspector',
                      headers=None):
        """Uploads a given string to Swift.

        :param object: The name of the object in Swift
        :param data: string data to put in the object
        :param container: The name of the container for the object.
        :param headers: the headers for the object to pass to Swift
        :returns: The Swift UUID of the object
        :raises: utils.Error, if any operation with Swift fails.
        """
        try:
            self.connection.put_container(container)
        except swift_exceptions.ClientException as e:
            err_msg = (_('Swift failed to create container %(container)s. '
                         'Error was: %(error)s') %
                       {'container': container, 'error': e})
            raise utils.Error(err_msg)

        if CONF.swift.delete_after > 0:
            headers = headers or {}
            headers['X-Delete-After'] = CONF.swift.delete_after

        try:
            obj_uuid = self.connection.put_object(container,
                                                  object,
                                                  data,
                                                  headers=headers)
        except swift_exceptions.ClientException as e:
            err_msg = (_('Swift failed to create object %(object)s in '
                         'container %(container)s. Error was: %(error)s') %
                       {'object': object, 'container': container, 'error': e})
            raise utils.Error(err_msg)

        return obj_uuid
