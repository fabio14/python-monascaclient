# (C) Copyright 2014-2017 Hewlett Packard Enterprise Development LP
#
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

import re
import sys
import warnings

import fixtures
from keystoneclient.v3 import client as ksclient
from mox3 import mox
from oslotest import base
from requests_mock.contrib import fixture as requests_mock_fixture
import six

from monascaclient import exc
import monascaclient.shell
from monascaclient.tests import fakes


class TestCase(base.BaseTestCase):

    def setUp(self):
        super(TestCase, self).setUp()

    def tearDown(self):
        super(TestCase, self).tearDown()

    def set_fake_env(self, fake_env):
        client_env = ('OS_USERNAME', 'OS_PASSWORD', 'OS_USER_DOMAIN_ID',
                      'OS_USER_DOMAIN_NAME', 'OS_PROJECT_ID',
                      'OS_PROJECT_NAME', 'OS_AUTH_URL', 'OS_REGION_NAME',
                      'OS_AUTH_TOKEN', 'OS_NO_CLIENT_AUTH', 'OS_SERVICE_TYPE',
                      'OS_DOMAIN_NAME', 'OS_DOMAIN_ID',
                      'OS_ENDPOINT_TYPE', 'MONASCA_API_URL')

        for key in client_env:
            self.useFixture(
                fixtures.EnvironmentVariable(key, fake_env.get(key)))

    # required for testing with Python 2.6
    def assertRegexpMatches(self, text, expected_regexp, msg=None):
        """Fail the test unless the text matches the regular expression."""
        if isinstance(expected_regexp, six.string_types):
            expected_regexp = re.compile(expected_regexp)
        if not expected_regexp.search(text):
            msg = msg or "Regexp didn't match"
            msg = '%s: %r not found in %r' % (
                msg, expected_regexp.pattern, text)
            raise self.failureException(msg)

    def shell_error(self, argstr, error_match):
        orig = sys.stderr
        sys.stderr = six.StringIO()
        _shell = monascaclient.shell.MonascaShell()
        e = self.assertRaises(Exception, _shell.main, argstr.split())  # noqa
        self.assertRegexpMatches(e.__str__(), error_match)
        err = sys.stderr.getvalue()
        sys.stderr.close()
        sys.stderr = orig
        return err


class ShellBase(TestCase):

    def setUp(self):
        super(ShellBase, self).setUp()
        self.requests_mock = self.useFixture(requests_mock_fixture.Fixture())

        self.m = mox.Mox()
        self.m.StubOutWithMock(ksclient, 'Client')
        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

        # Some tests set exc.verbose = 1, so reset on cleanup
        def unset_exc_verbose():
            exc.verbose = 0

        self.addCleanup(unset_exc_verbose)

    def shell(self, argstr):
        orig = sys.stdout
        try:
            sys.stdout = six.StringIO()
            _shell = monascaclient.shell.MonascaShell()
            _shell.main(argstr.split())
            self.subcommands = _shell.subcommands.keys()
        except SystemExit:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.assertEqual(0, exc_value.code)
        finally:
            out = sys.stdout.getvalue()
            sys.stdout.close()
            sys.stdout = orig

        return out


class ShellTestCommon(ShellBase):

    def setUp(self):
        super(ShellTestCommon, self).setUp()

    def test_help_unknown_command(self):
        self.assertRaises(exc.CommandError, self.shell, 'help foofoo')

    def test_help(self):
        required = [
            '^usage: monasca',
            '(?m)^See "monasca help COMMAND" for help on a specific command',
        ]
        for argstr in ['--help', 'help']:
            help_text = self.shell(argstr)
            for r in required:
                self.assertRegexpMatches(help_text, r)

    def test_command_help(self):
        output = self.shell('help help')
        self.assertIn('usage: monasca help [<subcommand>]', output)
        subcommands = list(self.subcommands)
        for command in subcommands:
            if command.replace('_', '-') == 'bash-completion':
                continue
            output1 = self.shell('help %s' % command)
            output2 = self.shell('%s --help' % command)
            self.assertEqual(output1, output2)
            self.assertRegexpMatches(output1, '^usage: monasca %s' % command)

    def test_help_on_subcommand(self):
        required = [
            '^usage: monasca metric-create',
            "(?m)^Create metric",
        ]
        argstrings = [
            'help metric-create',
        ]
        for argstr in argstrings:
            help_text = self.shell(argstr)
            for r in required:
                self.assertRegexpMatches(help_text, r)

    def test_deprecated_warning(self):
        argrequired = [('--help --os-tenant-name=this', '--os-tenant-name is deprecated'),
                       ('--help --os-tenant-id=this', '--os-tenant-id is deprecated')]
        for argstr, required in argrequired:
            with warnings.catch_warnings(record=True) as w:
                self.shell(argstr)
                self.assertEqual(str(w[0].message), required)
                self.assertEqual(w[0].category, DeprecationWarning)


class ShellTestMonascaCommands(ShellBase):

    def setUp(self):
        super(ShellTestMonascaCommands, self).setUp()
        self._set_fake_env()

    def assertHeaders(self, req=None, **kwargs):
        if not req:
            req = self.requests_mock.last_request

        self.assertEqual('abcd1234', req.headers['X-Auth-Token'])
        self.assertEqual('python-monascaclient', req.headers['User-Agent'])

        for k, v in kwargs.items():
            self.assertEqual(v, req.headers[k])

    def _set_fake_env(self):
        fake_env = {
            'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password',
            'OS_PROJECT_NAME': 'project_name',
            'OS_AUTH_URL': 'http://no.where',
        }
        self.set_fake_env(fake_env)

    def _script_keystone_client(self):
        fakes.script_keystone_client()

    def test_bad_metrics_create_subcommand(self):
        argstrings = [
            'metric-create metric1',
            'metric-create 123',
            'metric-create',
        ]
        _shell = monascaclient.shell.MonascaShell()
        for argstr in argstrings:
            self.assertRaises(SystemExit, _shell.main, argstr.split())

    def test_good_metrics_create_subcommand(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        headers = {'location': 'http://no.where/v2.0/metrics'}
        self.requests_mock.post('http://192.168.1.5:8004/v1/f14b41234/metrics',
                                status_code=204,
                                headers=headers)

        argstrings = [
            'metric-create metric1 123 --time 1395691090',
        ]
        for argstr in argstrings:
            retvalue = self.shell(argstr)
            self.assertRegexpMatches(retvalue, "^Success")

        data = {'timestamp': 1395691090,
                'name': 'metric1',
                'value': 123.0}

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

    def test_good_metrics_create_subcommand_with_tenant_id(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        headers = {'location': 'http://no.where/v2.0/metrics'}
        self.requests_mock.post('http://192.168.1.5:8004/v1/f14b41234/metrics',
                                status_code=204,
                                headers=headers)

        proj = 'd48e63e76a5c4e05ba26a1185f31d4aa'
        argstrings = [
            'metric-create metric1 123 --time 1395691090 --project-id ' + proj,
        ]
        for argstr in argstrings:
            retvalue = self.shell(argstr)
            self.assertRegexpMatches(retvalue, "^Success")

        data = {'timestamp': 1395691090,
                'name': 'metric1',
                'value': 123.0}

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

        request_url = self.requests_mock.last_request.url
        query_arg = request_url[request_url.index('?') + 1:]
        self.assertEqual('tenant_id=' + proj, query_arg)

    def test_bad_notifications_create_missing_args_subcommand(self):
        argstrings = [
            'notification-create email1 metric1@hp.com',
        ]
        _shell = monascaclient.shell.MonascaShell()
        for argstr in argstrings:
            self.assertRaises(SystemExit, _shell.main, argstr.split())

    def test_good_notifications_create_subcommand(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        url = 'http://192.168.1.5:8004/v1/f14b41234/notification-methods'
        headers = {'location': 'http://no.where/v2.0/notification-methods',
                   'Content-Type': 'application/json'}
        self.requests_mock.post(url,
                                status_code=201,
                                headers=headers,
                                json='id')

        argstrings = [
            'notification-create email1 EMAIL john.doe@hp.com',
        ]
        for argstr in argstrings:
            retvalue = self.shell(argstr)
            self.assertRegexpMatches(retvalue, "id")

        data = {'name': 'email1',
                'type': 'EMAIL',
                'address': 'john.doe@hp.com'}

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

    def test_good_notifications_create_subcommand_webhook(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        url = 'http://192.168.1.5:8004/v1/f14b41234/notification-methods'
        headers = {'location': 'http://no.where/v2.0/notification-methods',
                   'Content-Type': 'application/json'}
        self.requests_mock.post(url,
                                status_code=201,
                                headers=headers,
                                json='id')

        argstrings = [
            'notification-create mypost WEBHOOK http://localhost:8080',
        ]
        for argstr in argstrings:
            retvalue = self.shell(argstr)
            self.assertRegexpMatches(retvalue, "id")

        data = {'name': 'mypost',
                'type': 'WEBHOOK',
                'address': 'http://localhost:8080'}

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

    def test_good_notifications_patch(self):
        args = '--type EMAIL --address john.doe@hpe.com --period 0'
        data = {'type': 'EMAIL',
                'address': 'john.doe@hpe.com',
                'period': 0}
        self.run_notification_patch_test(args, data)

    def test_good_notifications_patch_just_name(self):
        name = 'fred'
        args = '--name ' + name
        data = {'name': name}
        self.run_notification_patch_test(args, data)

    def test_good_notifications_patch_just_address(self):
        address = 'fred@fl.com'
        args = '--address ' + address
        data = {'address': address}
        self.run_notification_patch_test(args, data)

    def test_good_notifications_patch_just_period(self):
        period = 0
        args = '--period ' + str(period)
        data = {'period': period}
        self.run_notification_patch_test(args, data)

    def run_notification_patch_test(self, args, data):
        self._script_keystone_client()
        self.m.ReplayAll()

        id_str = '0495340b-58fd-4e1c-932b-5e6f9cc96490'
        url = 'http://192.168.1.5:8004/v1/f14b41234/notification-methods/'
        headers = {'location': 'http://no.where/v2.0/notification-methods',
                   'Content-Type': 'application/json'}

        self.requests_mock.patch(url + id_str,
                                 status_code=201,
                                 headers=headers,
                                 json='id')

        argstring = 'notification-patch {0} {1}'.format(id_str, args)
        retvalue = self.shell(argstring)
        self.assertRegexpMatches(retvalue, "id")

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

    def test_bad_notifications_patch(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        id_str = '0495340b-58fd-4e1c-932b-5e6f9cc96490'
        argstring = 'notification-patch {0} --type EMAIL --address' \
                    ' john.doe@hpe.com --period 60'.format(id_str)

        retvalue = self.shell(argstring)
        self.assertRegexpMatches(retvalue, "^Invalid")

    def test_good_notifications_update(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        id_str = '0495340b-58fd-4e1c-932b-5e6f9cc96491'
        url = 'http://192.168.1.5:8004/v1/f14b41234/notification-methods/'
        headers = {'location': 'http://no.where/v2.0/notification-methods',
                   'Content-Type': 'application/json'}

        self.requests_mock.put(url + id_str,
                               status_code=201,
                               headers=headers,
                               json='id')

        argstring = 'notification-update {0} notification_updated_name ' \
                    'EMAIL john.doe@hpe.com 0'.format(id_str)
        retvalue = self.shell(argstring)
        self.assertRegexpMatches(retvalue, "id")

        data = {'name': 'notification_updated_name',
                'type': 'EMAIL',
                'address': 'john.doe@hpe.com',
                'period': 0}

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

    def test_good_alarm_definition_update(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        id_str = '0495340b-58fd-4e1c-932b-5e6f9cc96490'
        url = 'http://192.168.1.5:8004/v1/f14b41234/alarm-definitions/'
        headers = {'location': 'http://no.where/v2.0/notification-methods',
                   'Content-Type': 'application/json'}

        self.requests_mock.put(url + id_str,
                               status_code=201,
                               headers=headers,
                               json='id')

        cmd = 'alarm-definition-update'
        name = 'alarm_name'
        description = 'test_alarm_definition'
        expression = 'avg(Test_Metric_1)>=10'
        notif_id = '16012650-0b62-4692-9103-2d04fe81cc93'
        enabled = 'True'
        match_by = 'hostname'
        severity = 'CRITICAL'

        args = [cmd, id_str, name, description, expression, notif_id,
                notif_id, notif_id, enabled, match_by, severity]
        argstring = " ".join(args)
        retvalue = self.shell(argstring)
        self.assertRegexpMatches(retvalue, "id")

        data = {'name': name,
                'description': description,
                'expression': expression,
                'alarm_actions': [notif_id],
                'undetermined_actions': [notif_id],
                'ok_actions': [notif_id],
                'match_by': [match_by],
                'actions_enabled': bool(enabled),
                'severity': severity}

        self.assertHeaders()
        self.assertEqual(data, self.requests_mock.last_request.json())

    def test_notifications_types_list(self):
        self._script_keystone_client()
        self.m.ReplayAll()

        url = 'http://192.168.1.5:8004/v1/f14b41234/notification-methods/'
        headers = {'Content-Type': 'application/json'}
        body = [{"type": "WEBHOOK"}, {"type": "EMAIL"}, {"type": "PAGERDUTY"}]
        self.requests_mock.get(url + 'types', headers=headers, json=body)

        argstrings = ["notification-type-list"]

        retvalue = self.shell("".join(argstrings))
        self.assertRegexpMatches(retvalue, "types")

        self.assertHeaders()
