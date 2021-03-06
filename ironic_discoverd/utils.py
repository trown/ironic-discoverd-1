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

import logging
import re
import socket

import eventlet
from ironicclient import client
from ironicclient import exceptions
from keystonemiddleware import auth_token
from oslo_config import cfg
import six

from ironic_discoverd.common.i18n import _, _LE, _LI, _LW

CONF = cfg.CONF

# See http://specs.openstack.org/openstack/ironic-specs/specs/kilo/new-ironic-state-machine.html  # noqa
VALID_STATES = {'enroll', 'manageable', 'inspecting', 'inspectfail'}


LOG = logging.getLogger('ironic_discoverd.utils')
RETRY_COUNT = 12
RETRY_DELAY = 5


class Error(Exception):
    """Discoverd exception."""

    def __init__(self, msg, code=400):
        super(Error, self).__init__(msg)
        LOG.error(msg)
        self.http_code = code


def get_client():  # pragma: no cover
    """Get Ironic client instance."""
    args = dict({'os_password': CONF.discoverd.os_password,
                 'os_username': CONF.discoverd.os_username,
                 'os_auth_url': CONF.discoverd.os_auth_url,
                 'os_tenant_name': CONF.discoverd.os_tenant_name})
    return client.get_client(1, **args)


def add_auth_middleware(app):
    """Add authentication middleware to Flask application.

    :param app: application.
    """
    auth_conf = dict({'admin_password': CONF.discoverd.os_password,
                      'admin_user': CONF.discoverd.os_username,
                      'auth_uri': CONF.discoverd.os_auth_url,
                      'admin_tenant_name': CONF.discoverd.os_tenant_name})
    auth_conf['delay_auth_decision'] = True
    auth_conf['identity_uri'] = CONF.discoverd.identity_uri
    app.wsgi_app = auth_token.AuthProtocol(app.wsgi_app, auth_conf)


def check_auth(request):
    """Check authentication on request.

    :param request: Flask request
    :raises: utils.Error if access is denied
    """
    if not CONF.discoverd.authenticate:
        return
    if request.headers.get('X-Identity-Status').lower() == 'invalid':
        raise Error(_('Authentication required'), code=401)
    roles = (request.headers.get('X-Roles') or '').split(',')
    if 'admin' not in roles:
        LOG.error(_LE('Role "admin" not in user role list %s'), roles)
        raise Error(_('Access denied'), code=403)


def is_valid_mac(address):
    """Return whether given value is a valid MAC."""
    m = "[0-9a-f]{2}(:[0-9a-f]{2}){5}$"
    return (isinstance(address, six.string_types)
            and re.match(m, address.lower()))


def get_ipmi_address(node):
    # All these are kind-of-ipmi
    for name in ('ipmi_address', 'ilo_address', 'drac_host'):
        value = node.driver_info.get(name)
        if value:
            try:
                ip = socket.gethostbyname(value)
                return ip
            except socket.gaierror:
                msg = ('Failed to resolve the hostname (%s) for node %s')
                raise Error(msg % (value, node.uuid))


def retry_on_conflict(call, *args, **kwargs):
    """Wrapper to retry 409 CONFLICT exceptions."""
    for i in range(RETRY_COUNT):
        try:
            return call(*args, **kwargs)
        except exceptions.Conflict as exc:
            LOG.warning(_LW('Conflict on calling %(call)s: %(exc)s,'
                            ' retry attempt %(count)d') %
                        {'call': getattr(call, '__name__', repr(call)),
                         'exc': exc,
                         'count': i + 1})
            if i == RETRY_COUNT - 1:
                raise
            eventlet.greenthread.sleep(RETRY_DELAY)

    raise RuntimeError('unreachable code')  # pragma: no cover


def check_provision_state(node):
    if not node.maintenance:
        provision_state = node.provision_state
        if provision_state and provision_state.lower() not in VALID_STATES:
            msg = _('Refusing to introspect node %(node)s with provision state'
                    ' "%(state)s" and maintenance mode off')
            raise Error(msg % {'node': node.uuid, 'state': provision_state})
    else:
        LOG.info(_LI('Node %s is in maintenance mode, skipping'
                     ' provision states check'), node.uuid)


def capabilities_to_dict(caps):
    """Convert the Node's capabilities into a dictionary."""
    if not caps:
        return {}
    return dict([key.split(':', 1) for key in caps.split(',')])


def dict_to_capabilities(caps_dict):
    """Convert a dictionary into a string with the capabilities syntax."""
    return ','.join(["%s:%s" % (key, value)
                     for key, value in caps_dict.items()])
