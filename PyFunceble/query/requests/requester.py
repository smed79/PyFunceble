"""
The tool to check the availability or syntax of domain, IP or URL.

::


    ██████╗ ██╗   ██╗███████╗██╗   ██╗███╗   ██╗ ██████╗███████╗██████╗ ██╗     ███████╗
    ██╔══██╗╚██╗ ██╔╝██╔════╝██║   ██║████╗  ██║██╔════╝██╔════╝██╔══██╗██║     ██╔════╝
    ██████╔╝ ╚████╔╝ █████╗  ██║   ██║██╔██╗ ██║██║     █████╗  ██████╔╝██║     █████╗
    ██╔═══╝   ╚██╔╝  ██╔══╝  ██║   ██║██║╚██╗██║██║     ██╔══╝  ██╔══██╗██║     ██╔══╝
    ██║        ██║   ██║     ╚██████╔╝██║ ╚████║╚██████╗███████╗██████╔╝███████╗███████╗
    ╚═╝        ╚═╝   ╚═╝      ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═════╝ ╚══════╝╚══════╝

Provides our own requests handler

Author:
    Nissar Chababy, @funilrys, contactTATAfunilrysTODTODcom

Special thanks:
    https://pyfunceble.github.io/#/special-thanks

Contributors:
    https://pyfunceble.github.io/#/contributors

Project link:
    https://github.com/funilrys/PyFunceble

Project documentation:
    https://docs.pyfunceble.com

Project homepage:
    https://pyfunceble.github.io/

License:
::


    Copyright 2017, 2018, 2019, 2020, 2022, 2023, 2024 Nissar Chababy

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        https://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
"""

import functools
import logging
import warnings
from typing import Optional, Union

import requests
import requests.exceptions
import urllib3.exceptions
from box import Box

import PyFunceble.storage
from PyFunceble.dataset.user_agent import UserAgentDataset
from PyFunceble.query.dns.query_tool import DNSQueryTool
from PyFunceble.query.requests.adapter.http import RequestHTTPAdapter
from PyFunceble.query.requests.adapter.https import RequestHTTPSAdapter


class Requester:
    """
    Provides our very own requests handler.

    :param int max_retries:
        Optional, The maximum number of retries to perform.
    :param bool verify_certificate:
        Optional, Should we verify and validate the SSL/TLS certificate ?
    :param float timeout:
        Optional, The timeout to apply to the query.
    :param int max_redirects:
        Optional, The maximum number of redirects to allow.
    :param dns_query_tool:
        Optional, The DNS Query tool to use.
    :param proxy_pattern:
        Optional, The proxy pattern to apply to each query.

        Expected format:

            ::
                {
                    "global": {
                        # Everything under global will be used as default if no
                        # rule matched.

                        "http": "str" ## HTTP_PROXY
                        "https": "str" ## HTTPS_PROXY
                    },
                    "rules":[
                        # A set/list of rules to work with.

                        {
                            "http": "str" ## HTTP_PROXY when TLD is matched.
                            "https": "str" ## HTTPS_PROXY when TLD is matched.
                            "tld": [
                                "str",
                                "str",
                                str
                            ]
                        },
                        {
                            "http": "str" ## HTTP_PROXY when TLD is matched.
                            "https": "str" ## HTTPS_PROXY when TLD is matched.
                            "tld": [
                                "str",
                                "str"
                            ]
                        },
                    ]
                }
    """

    STD_VERIFY_CERTIFICATE: bool = False
    STD_TIMEOUT: float = 3.0
    STD_MAX_RETRIES: int = 3

    urllib3_exceptions = urllib3.exceptions
    exceptions = requests.exceptions

    _timeout: float = 5.0
    _max_retries: int = 3
    _verify_certificate: bool = True
    _max_redirects: int = 60
    _proxy_pattern: dict = {}

    config: Optional[Box] = None

    session: Optional[requests.Session] = None
    dns_query_tool: Optional[DNSQueryTool] = None

    def __init__(
        self,
        *,
        max_retries: Optional[int] = None,
        verify_certificate: Optional[bool] = None,
        timeout: Optional[float] = None,
        max_redirects: Optional[int] = None,
        dns_query_tool: Optional[DNSQueryTool] = None,
        proxy_pattern: Optional[dict] = None,
        config: Optional[Box] = None,
    ) -> None:
        if config is not None:
            self.config = config
        else:
            self.config = Box({}, default_box=True)

        if max_retries is not None:
            self.max_retries = max_retries
        else:
            self.guess_and_set_max_retries()

        if verify_certificate is not None:
            self.verify_certificate = verify_certificate
        else:
            self.guess_and_set_verify_certificate()

        if timeout is not None:
            self.timeout = timeout
        else:
            self.guess_and_set_timeout()

        if max_redirects is not None:
            self.max_redirects = max_redirects

        if dns_query_tool is not None:
            self.dns_query_tool = dns_query_tool
        else:
            self.dns_query_tool = DNSQueryTool()

        if proxy_pattern is not None:
            self.proxy_pattern = proxy_pattern
        else:
            self.guess_and_set_proxy_pattern()

        self.session = self.get_session()

        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        logging.getLogger("requests.packages.urllib3").setLevel(logging.CRITICAL)
        logging.getLogger("urllib3").setLevel(logging.CRITICAL)

    def recreate_session(func):  # pylint: disable=no-self-argument
        """
        Recreate a new session after executing the decorated method.
        """

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)  # pylint: disable=not-callable

            if hasattr(self, "session") and isinstance(self.session, requests.Session):
                self.session = self.get_session()

            return result

        return wrapper

    def request_factory(verb: str):  # pylint: disable=no-self-argument
        """
        Provides a universal request factory.

        :param verb:
            The HTTP Verb to apply.
        """

        def request_method(func):
            @functools.wraps(func)
            def wrapper(self, *args, **kwargs):
                # pylint: disable=no-member
                req = getattr(self.session, verb.lower())(*args, **kwargs)
                return req

            return wrapper

        return request_method

    @property
    def headers(self) -> dict:
        """
        Provides the headers to use.
        """

        return self.session.headers

    @headers.setter
    @recreate_session
    def headers(self, value: dict) -> None:
        """
        Sets the headers to use.

        :param value:
            The headers to set.
        """

        self.session.headers.update(value)

    def set_config(self, config: Box) -> "Requester":
        """
        Sets the configuration to work with.

        :param config:
            The configuration to work with.
        """

        self.config = config

        return self

    @property
    def max_retries(self) -> int:
        """
        Provides the current state of the :code:`_max_retries` attribute.
        """

        return self._max_retries

    @max_retries.setter
    @recreate_session
    def max_retries(self, value: int) -> None:
        """
        Sets the max retries value to apply to all subsequent requests.

        :param value:
            The value to set.

        :raise TypeError:
            When the given :code:`value` is not a :py:class:`int`.
        :raise ValueError:
            When the given :code:`value` is less than :code:`1`.
        """

        if not isinstance(value, int):
            raise TypeError(f"<value> should be {int}, {type(value)} given.")

        if value < 0:
            raise ValueError(f"<value> ({value!r}) should be positive.")

        self._max_retries = value

    def set_max_retries(self, value: int) -> "Requester":
        """
        Sets the max retries value to apply to all subsequent requests.

        :param value:
            The value to set.
        """

        self.max_retries = value

        return self

    def guess_and_set_max_retries(self) -> "Requester":
        """
        Try to guess the value from the configuration and set it.
        """

        try:
            if isinstance(self.config.max_http_retries, int):
                self.set_max_retries(self.config.max_http_retries)
            else:
                self.set_max_retries(self.STD_MAX_RETRIES)
        except:  # pylint: disable=bare-except
            self.set_max_retries(self.STD_MAX_RETRIES)

        return self

    @property
    def max_redirects(self) -> int:
        """
        Provides the current state of the :code:`_max_redirects` attribute.
        """

        return self._max_redirects

    @max_redirects.setter
    @recreate_session
    def max_redirects(self, value: int) -> None:
        """
        Sets the max redirects value to apply to all subsequent requests.

        :param value:
            The value to set.

        :raise TypeError:
            When the given :code:`value` is not a :py:class:`int`.
        :raise ValueError:
            When the given :code:`value` is less than :code:`1`.
        """

        if not isinstance(value, int):
            raise TypeError(f"<value> should be {int}, {type(value)} given.")

        if value < 1:
            raise ValueError(f"<value> ({value!r}) should not be less than 1.")

        self._max_redirects = value

    def set_max_redirects(self, value: int) -> "Requester":
        """
        Sets the max redirects value to apply to all subsequent requests.

        :param value:
            The value to set.
        """

        self.max_redirects = value

        return self

    @property
    def verify_certificate(self) -> bool:
        """
        Provides the current state of the :code:`_verify_certificate` attribute.
        """

        return self._verify_certificate

    @verify_certificate.setter
    @recreate_session
    def verify_certificate(self, value: bool) -> None:
        """
        Enable or disables the certificate validation.

        :param value:
            The value to set.

        :raise TypeError:
            When the given :code:`value` is not a :py:class`bool`.
        """

        if not isinstance(value, bool):
            raise TypeError(f"<value> shoule be {bool}, {type(value)} given.")

        self._verify_certificate = value

    def set_verify_certificate(self, value: bool) -> "Requester":
        """
        Enable or disables the certificate validation.

        :param value:
            The value to set.
        """

        self.verify_certificate = value

        return self

    def guess_and_set_verify_certificate(self) -> "Requester":
        """
        Try to guess the value from the configuration and set it.
        """

        try:
            if isinstance(self.config.verify_ssl_certificate, bool):
                self.set_verify_certificate(self.config.verify_ssl_certificate)
            else:
                self.set_verify_certificate(self.STD_VERIFY_CERTIFICATE)
        except:  # pylint: disable=bare-except
            self.set_max_retries(self.STD_MAX_RETRIES)

        return self

    @property
    def timeout(self) -> float:
        """
        Provides the current state of the :code:`_timeout` attribute.
        """

        return self._timeout

    @timeout.setter
    @recreate_session
    def timeout(self, value: Union[int, float]) -> None:
        """
        Enable or disables the certificate validation.

        :param value:
            The value to set.

        :raise TypeError:
            When the given :code:`value` is not a :py:class`int` nor
            :py:class:`float`.
        :raise ValueError:
            Whent the given :code:`value` is less than `1`.
        """

        if not isinstance(value, (int, float)):
            raise TypeError(f"<value> shoule be {int} or {float}, {type(value)} given.")

        if value < 0:
            raise ValueError("<value> should not be less than 0.")

        self._timeout = float(value)

    def set_timeout(self, value: Union[int, float]) -> "Requester":
        """
        Enable or disables the certificate validation.

        :param value:
            The value to set.
        """

        self.timeout = value

        return self

    def guess_and_set_timeout(self) -> "Requester":
        """
        Try to guess the value from the configuration and set it.
        """

        try:
            if isinstance(self.config.lookup.timeout, (int, float)):
                self.set_timeout(self.config.lookup.timeout)
            else:
                self.set_timeout(self.STD_TIMEOUT)
        except:  # pylint: disable=bare-except
            self.set_timeout(self.STD_TIMEOUT)

        return self

    @property
    def proxy_pattern(self) -> Optional[dict]:
        """
        Provides the current state of the :code:`_proxy_pattern` attribute.
        """

        return self._proxy_pattern

    @proxy_pattern.setter
    @recreate_session
    def proxy_pattern(self, value: dict) -> None:
        """
        Overwrite the proxy pattern to use.

        :param value:
            The value to set.

        :raise TypeError:
            When the given :code:`value` is not a :py:class`dict`.
        """

        if not isinstance(value, dict):
            raise TypeError(f"<value> shoule be {dict}, {type(value)} given.")

        self._proxy_pattern = value

    def set_proxy_pattern(self, value: dict) -> "Requester":
        """
        Overwrite the proxy pattern.

        :param value:
            The value to set.
        """

        self.proxy_pattern = value

        return self

    def guess_and_set_proxy_pattern(self) -> "Requester":
        """
        Try to guess the value from the configuration and set it.
        """

        try:
            if self.config.proxy:
                self.set_proxy_pattern(self.config.proxy)
            else:
                self.set_proxy_pattern({})
        except:  # pylint: disable=bare-except
            self.set_proxy_pattern({})

        return self

    def guess_all_settings(self) -> "Requester":
        """
        Try to guess all settings.
        """

        to_ignore = ["guess_all_settings"]

        for method in dir(self):
            if method in to_ignore or not method.startswith("guess_"):
                continue

            getattr(self, method)()

        return self

    def get_verify_certificate(self) -> bool:
        """
        Provides the current value of the certificate validation.
        """

        return self.verify_certificate

    def get_timeout(self) -> float:
        """
        Provides the currently set timetout.
        """

        return self.timeout

    def get_session(self) -> requests.Session:
        """
        Provides a new session.
        """

        session = requests.Session()

        session.verify = self.verify_certificate
        session.max_redirects = self.max_redirects
        session.mount(
            "https://",
            RequestHTTPSAdapter(
                max_retries=self.max_retries,
                timeout=self.timeout,
                dns_query_tool=self.dns_query_tool,
                proxy_pattern=self.proxy_pattern,
            ),
        )
        session.mount(
            "http://",
            RequestHTTPAdapter(
                max_retries=self.max_retries,
                timeout=self.timeout,
                dns_query_tool=self.dns_query_tool,
                proxy_pattern=self.proxy_pattern,
            ),
        )

        if PyFunceble.storage.USER_AGENTS:
            custom_headers = {"User-Agent": UserAgentDataset().get_latest()}
        else:
            custom_headers = {}

        session.headers.update(custom_headers)

        return session

    @request_factory("GET")
    def get(self, *args, **kwargs) -> requests.Response:
        """
        Sends a GET request and get its response.
        """

    @request_factory("OPTIONS")
    def options(self, *args, **kwargs) -> requests.Response:
        """
        Sends am OPTIONS request and get its response.
        """

    @request_factory("HEAD")
    def head(self, *args, **kwargs) -> requests.Response:
        """
        Sends a HEAD request and get its response.
        """

    @request_factory("POST")
    def post(self, *args, **kwargs) -> requests.Response:
        """
        Sends a POST request and get its response.
        """

    @request_factory("PUT")
    def put(self, *args, **kwargs) -> requests.Response:
        """
        Sends a PUT request and get its response.
        """

    @request_factory("PATCH")
    def patch(self, *args, **kwargs) -> requests.Response:
        """
        Sends a PATCH request and get its response.
        """

    @request_factory("DELETE")
    def delete(self, *args, **kwargs) -> requests.Response:
        """
        Sends a DELETE request and get its response.
        """
