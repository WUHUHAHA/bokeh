#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2019, Anaconda, Inc., and Bokeh Contributors.
# All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Boilerplate
#-----------------------------------------------------------------------------
from __future__ import absolute_import, division, print_function, unicode_literals

import pytest ; pytest

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

# Standard library imports
import codecs
import json
import os
import random

from mock import patch

# External imports

# Bokeh imports
from bokeh.util.string import decode_utf8
from bokeh.util.session_id import (generate_session_id,
                                   generate_secret_key,
                                   check_session_id_signature,
                                   _get_sysrandom,
                                   _signature,
                                   _reseed_if_needed,
                                   _base64_decode,
                                   _base64_encode)

# Module under test
import bokeh.util.session_id

#-----------------------------------------------------------------------------
# Setup
#-----------------------------------------------------------------------------

def _nie():
    def func():
        raise NotImplementedError()
    return func

_MERSENNE_MSG = 'A secure pseudo-random number generator is not available on your system. Falling back to Mersenne Twister.'

#-----------------------------------------------------------------------------
# General API
#-----------------------------------------------------------------------------

class TestSessionId(object):
    def test_base64_roundtrip(self):
        for s in [ "", "a", "ab", "abc", "abcd", "abcde", "abcdef", "abcdefg",
                   "abcdefgh", "abcdefghi",
                   "abcdefghijklmnopqrstuvwxyz" ]:
            assert s == _base64_decode(_base64_encode(s), encoding='utf-8')

    def test_reseed_if_needed(self):
        # we have to set a seed in order to be able to get state
        random.seed(codecs.encode("abcdefg", "utf-8"))
        state = random.getstate()
        _reseed_if_needed(using_sysrandom=True, secret_key=None)
        # did NOT reseed
        assert state == random.getstate()
        # monkeypatch
        saved = bokeh.util.session_id.random
        try:
            bokeh.util.session_id.random = random
            _reseed_if_needed(using_sysrandom=False, secret_key="abc")
            # DID reseed
            assert state != random.getstate()
        finally:
            bokeh.util.session_id.random = saved

    def test_signature(self):
        sig = _signature("xyz", secret_key="abc")
        with_same_key = _signature("xyz", secret_key="abc")
        assert sig == with_same_key
        with_different_key = _signature("xyz", secret_key="qrs")
        assert sig != with_different_key

    def test_generate_unsigned(self):
        token = generate_session_id(signed=False)
        assert '.' not in token
        assert 83 == len(token)
        assert "session_id" in json.loads(_base64_decode(token, encoding='utf-8'))

        another_token = generate_session_id(signed=False)
        assert '.' not in another_token
        assert 83 == len(another_token)
        assert "session_id" in json.loads(_base64_decode(another_token, encoding='utf-8'))

        assert token != another_token

    def test_payload_unsigned(self):
        token = generate_session_id(signed=False, extra_payload=dict(foo=10))
        assert '.' not in token
        payload = json.loads(_base64_decode(token, encoding='utf-8'))
        assert payload['foo'] == 10

    def test_payload_error_unsigned(self):
        with pytest.raises(RuntimeError):
            generate_session_id(signed=False, extra_payload=dict(session_id=10))

    def test_generate_signed(self):
        token = generate_session_id(signed=True, secret_key="abc")
        assert '.' in token
        assert check_session_id_signature(token, secret_key="abc", signed=True)
        assert not check_session_id_signature(token, secret_key="qrs", signed=True)
        payload, sig = token.split('.')
        assert "session_id" in json.loads(_base64_decode(payload, encoding='utf-8'))

    def test_payload_signed(self):
        token = generate_session_id(signed=True, secret_key="abc", extra_payload=dict(foo=10))
        assert '.' in token
        assert check_session_id_signature(token, secret_key="abc", signed=True)
        assert not check_session_id_signature(token, secret_key="qrs", signed=True)
        payload, sig = token.split('.')
        payload = json.loads(_base64_decode(payload, encoding='utf-8'))
        assert payload['foo'] == 10

    def test_payload_error_signed(self):
        with pytest.raises(RuntimeError):
            generate_session_id(signed=False, secret_key="abc", extra_payload=dict(session_id=10))

    def test_check_signature_of_unsigned(self):
        session_id = generate_session_id(signed=False, secret_key="abc") # secret shouldn't be used
        assert not check_session_id_signature(session_id, secret_key="abc", signed=True)

    def test_check_signature_of_empty_string(self):
        assert not check_session_id_signature("", secret_key="abc", signed=True)

    def test_check_signature_of_junk_with_hyphen_in_it(self):
        assert not check_session_id_signature("foo-bar-baz", secret_key="abc", signed=True)

    def test_check_signature_of_junk_with_dots_in_it(self):
        assert not check_session_id_signature("foo.bar.baz", secret_key="abc", signed=True)

    def test_check_signature_with_signing_disabled(self):
        assert check_session_id_signature("gobbledygook", secret_key="abc", signed=False)

    def test_generate_secret_key(self):
        key = generate_secret_key()
        assert 44 == len(key)
        key2 = generate_secret_key()
        assert 44 == len(key2)
        assert key != key2

    def test_string_encoding_does_not_affect_session_id_check(self):
        # originates from #6653
        session_id = generate_session_id(signed=True, secret_key="abc")
        assert check_session_id_signature(session_id, secret_key="abc", signed=True)
        assert check_session_id_signature(decode_utf8(session_id), secret_key="abc", signed=True)

#-----------------------------------------------------------------------------
# Dev API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Private API
#-----------------------------------------------------------------------------

class Test__get_sysrandom(object):

    def test_default(self):
        import random
        try:
            random.SystemRandom()
            expected = True
        except NotImplementedError:
            expected = False
        _random, using_sysrandom = _get_sysrandom()
        assert using_sysrandom == expected

    @patch('random.SystemRandom', new_callable=_nie)
    def test_missing_sysrandom_no_secret_key(self, _mock_sysrandom):
        with pytest.warns(UserWarning) as warns:
            random, using_sysrandom = _get_sysrandom()
            assert not using_sysrandom
            assert len(warns) == 2
            assert warns[0].message.args[0] == _MERSENNE_MSG
            assert warns[1].message.args[0] == (
                'A secure pseudo-random number generator is not available '
                'and no BOKEH_SECRET_KEY has been set. '
                'Setting a secret key will mitigate the lack of a secure '
                'generator.'
            )

    @patch('random.SystemRandom', new_callable=_nie)
    def test_missing_sysrandom_with_secret_key(self, _mock_sysrandom):
        os.environ["BOKEH_SECRET_KEY"] = "foo"
        with pytest.warns(UserWarning) as warns:
            random, using_sysrandom = _get_sysrandom()
            assert not using_sysrandom
            assert len(warns) == 1
            assert warns[0].message.args[0] == _MERSENNE_MSG
        del os.environ["BOKEH_SECRET_KEY"]

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------
