"""Provide python interface to GeoNature API.


Methods, see each class

Properties:

- transfer_errors            - Return number of HTTP errors

Exceptions:

- BiolovisionApiException    - General exception
- HTTPError                  - HTTP protocol error
- MaxChunksError             - Too many chunks returned from API calls
- IncorrectParameter         - Incorrect or missing parameter

"""
import sys
import json
import logging
import time
from urllib import parse
from functools import lru_cache

from typing import Dict
import requests
from . import _, __version__

logger = logging.getLogger("transfer_gn.geonature_api")


class HashableDict(dict):
    """Provide hashable dict type, to enable @lru_cache."""

    def __hash__(self):
        return hash(frozenset(self))


class GeoNatureApiException(Exception):
    """An exception occurred while handling your request."""


class HTTPError(GeoNatureApiException):
    """An HTTP error occurred."""


class MaxChunksError(GeoNatureApiException):
    """Too many chunks returned from API calls."""


class NotImplementedException(GeoNatureApiException):
    """Feature not implemented."""


class IncorrectParameter(GeoNatureApiException):
    """Incorrect or missing parameter."""


class Session:
    """[summary]

    Raises:
        NotImplementedException: [description]
        HTTPError: [description]
        HTTPError: [description]
        HTTPError: [description]
        MaxChunksError: [description]
        an: [description]
        IncorrectParameter: [description]

    Returns:
        [type]: [description]
    """


class GeoNatureAPI:
    """Top class, not for direct use. Provides internal and template methods."""

    def __init__(self, config, controler, max_retry=None, max_requests=None):
        self._config = config
        if max_retry is None:
            max_retry = config.max_retry
        if max_requests is None:
            max_requests = config.max_requests
        self._limits = {"max_retry": max_retry, "max_requests": max_requests}
        self._transfer_errors = 0
        self._http_status = 0
        self._ctrl = controler
        url = config.url if config.url[-1:] == "/" else config.url + "/"
        self._api_url = url + "api/"  # API Url

        # init session
        self._session = requests.Session()
        self._session.headers = {"Content-Type": "application/json"}
        auth_payload = json.dumps(
            {
                "login": config.user_name,
                "password": config.user_password,
                "id_application": config.id_application,
            }
        )
        login = self._session.post(
            self._api_url + "auth/login",
            data=auth_payload,
        )
        try:
            if login.status_code == 200:
                logger.info(
                    f"Successfully logged in into GeoNature named {self._config.name}"
                )
            else:
                logger.critical(
                    f"Log in GeoNature named {self._config.name} failed with status code {login.status_code}, cause: {json.loads(login.content)['msg']}"
                )

        except:
            logger.critical("Session failed")
            raise HTTPError(login.status_code)

        #  Find exports api path
        try:
            m = self._session.get(self._api_url + "gn_commons/modules")
            logger.info(
                _(f"Modules API status code is {m.status_code} for url {m.url}")
            )
            if m.status_code == 200:
                modules = json.loads(m.content)
                for item in modules:
                    if item["module_code"] == "EXPORTS":
                        self._export_api_path = item["module_path"]
                        logger.debug(f"Export api path is {self._export_api_path}")
                        break
            else:
                logger.critical(
                    f"Get GeoNature modules failedwith status code {m.status_code}, cause: {json.loads(m.content)['msg']}"
                )
        except Exception as e:
            logger.critical(f"Find export module failed, {e}")
            raise HTTPError(login.status_code)

    @property
    def version(self) -> str:
        """Return version."""
        return __version__

    @property
    def transfer_errors(self) -> int:
        """Return the number of HTTP errors during this session."""
        return self._transfer_errors

    @property
    def http_status(self) -> int:
        """Return the latest HTTP status code."""
        return self._http_status

    @property
    def controler(self) -> str:
        """Return the controler name."""
        return self._ctrl

    def _url_get(
        self,
        scope: str,
        params: dict = {},
        method: str = "GET",
        body: any = None,
        optional_headers: dict = None,
    ) -> dict:
        """Prepare the URL header, perform HTTP request and get json content.
        Test HTTP status and returns None if error, else return decoded json content.
        Increments _transfer_errors in case of error.

        Args:
            scope (str): scope is the export id to be queried.
            method (str, optional): HTTP method to use: GET/POST/DELETE/PUT. Default to GET. Defaults to "GET".
            body (any, optional): Optional body for POST or PUT. Defaults to None.
            optional_headers (dict, optional): Optional headers for request. Defaults to None.

        Raises:
            HTTPError: HTTP protocol error, returned as argument.

        Returns:
            dict: dict decoded from json if status OK, else None.
        """
        # Loop on chunks
        data_rec = None
        # Remove DEBUG logging level to avoid too many details
        # level = logging.getLogger().level
        # logging.getLogger().setLevel(logging.INFO)
        payload = parse.urlencode(params, quote_via=parse.quote)
        logger.debug(_("Params: %s"), payload)
        # Prepare call to API
        protected_url = self._api_url + scope
        if method == "GET":
            resp = self._session.get(url=protected_url, params=payload)
        elif method == "POST":
            resp = requests.post(url=protected_url, params=payload)
        elif method == "PUT":
            resp = requests.put(url=protected_url, params=payload)
        elif method == "DELETE":
            resp = requests.delete(url=protected_url, params=payload)
        else:
            raise NotImplementedException

        # logging.getLogger().setLevel(level)
        logger.debug(
            f"{method} status code = {resp.status_code}, for URL {protected_url}"
        )
        self._http_status = resp.status_code
        if self._http_status >= 300:
            # Request returned an error.
            # Logging and checking if not too many errors to continue
            logger.error(
                f"{method} status code = {resp.status_code}, for URL {protected_url}"
            )
            if (self._http_status >= 400) and (
                self._http_status <= 499
            ):  # pragma: no cover
                # Unreceverable error
                logger.critical(
                    f"Unreceverable error {self._http_status}, raising exception"
                )
                raise HTTPError(resp.status_code)
            self._transfer_errors += 1  # pragma: no cover
            if self._http_status == 503:  # pragma: no cover
                # Service unavailable: long wait
                time.sleep(self._config.tuning_unavailable_delay)
            else:
                # A transient error: short wait
                time.sleep(self._config.tuning_retry_delay)
            if self._transfer_errors > self._limits["max_retry"]:  # pragma: no cover
                # Too many retries. Raising exception
                logger.critical(
                    f"Too many error {self._transfer_errors}, raising exception"
                )
                raise HTTPError(resp.status_code)
        else:
            # No error from request: processing response if needed
            if method in ["PUT", "DELETE"]:
                # No response expected
                presp = json.loads("{}")
            else:
                try:
                    presp = resp.json()
                except json.decoder.JSONDecodeError:  # pragma: no cover
                    # Error during JSON decoding =>
                    # Logging error and no further processing of empty chunk
                    presp = json.loads("{}")
                    logger.error(f"Incorrect response content: {resp.text}")
                    logger.exception("Exception raised during JSON decoding")
                    raise HTTPError("resp.json exception")

            # Initialize or append to response dict, depending on content
            data = False
            max_offset = int(presp["total_filtered"] / presp["limit"]) - 1
            offset = 0
            logger.debug(f"{','.join([k for k in presp.keys()])}")
            if "items" in presp:
                if len(presp["items"]) > 0:
                    data = True
                    logger.debug(
                        f"Received {len(presp['items'])} data in {max_offset} pages"
                    )
                    if max_offset == 0:
                        data_rec = presp["items"]
                    else:
                        data_rec += presp["items"]

            else:
                logger.debug(f"Received non-data response: {presp}")
                if max_offset == 0:
                    data_rec = presp
                else:
                    data_rec += presp

            # Is there more data to come?
            if max_offset > 0:
                logger.debug(f"getting page {offset}")
                offset += 1

        logger.debug(f"Received {max_offset} pages")

        return data_rec

    def _api_list(self, opt_params=None, optional_headers=None):
        """Query for a list of entities of the given controler.

        Calls /ctrl API.

        Parameters
        ----------
        opt_params : HashableDict (to enable lru_cache)
            optional URL parameters, empty by default.
            See Biolovision API documentation.
        optional_headers : dict
            Optional body for GET request

        Returns
        -------
        json : dict or None
            dict decoded from json if status OK, else None
        """
        # Mandatory parameters.
        params = {}
        if opt_params is not None:
            params.update(opt_params)
        logger.debug(
            _(
                f"List from:{self._ctrl}, params: {params}, optional_headers:{optional_headers}"
            )
        )
        # GET from API
        entities = self._url_get(params, self._ctrl, optional_headers=optional_headers)[
            "data"
        ]
        logger.debug(_(f"Number of entities = {len(entities)}"))
        return {"data": entities}

    # -----------------------------------------
    #  Generic methods, used by most subclasses
    # -----------------------------------------

    def api_get(self, id_entity, **kwargs):
        """Query for a single entity of the given controler.

        Calls  /ctrl/id API.

        Parameters
        ----------
        id_entity : str
            entity to retrieve.
        **kwargs :
            optional URL parameters, empty by default.
            See Biolovision API documentation.

        Returns
        -------
        json : dict or None
            dict decoded from json if status OK, else None
        """
        # Mandatory parameters.
        params = {}
        for key, value in kwargs.items():
            params[key] = value
        logger.debug(
            _("In api_get for controler:%s, with parameters:%s"),
            id_entity,
            params,
        )
        # GET from API
        return self._url_get(params, self._ctrl + "/" + str(id_entity))

    def api_list(self, opt_params=None, optional_headers=None):
        """Query for a list of entities of the given controler.

        Calls /ctrl API.

        Parameters
        ----------
        opt_params : dict
            optional URL parameters, empty by default.
            See Biolovision API documentation.
        optional_headers : dict
            Optional body for GET request

        Returns
        -------
        json : dict or None
            dict decoded from json if status OK, else None
        """
        h_params = None if opt_params is None else HashableDict(opt_params)
        return self._api_list(opt_params=h_params, optional_headers=h_headers)

    # -------------------------
    # Exception testing methods
    # -------------------------
    def wrong_api(self):
        """Query for a wrong api.

        Calls /error API to raise an exception.

        """
        # Mandatory parameters.
        params = {
            "user_email": self._config.user_email,
            "user_pw": self._config.user_pw,
        }
        # GET from API
        return self._url_get(params, "error/")


class SyntheseAPI(GeoNatureAPI):
    """Implement api calls to observations controler.

    Methods:

    - api_get      - Return a single observations from the controler

    - api_list     - Return a list of observations from the controler

    - api_diff     - Return all changes in observations since a given date

    - api_search   - Search for observations based on parameter value

    """

    def __init__(self, config, max_retry=None, max_requests=None):
        super().__init__(config, "observations", max_retry, max_requests)

    def api_list(self, **kwargs):
        """Query for list of observations by taxo_group from the controler.

        Calls  /observations API.

        Parameters
        ----------
        id_taxo_group : integer
            taxo_group to query for observations
        **kwargs :
            optional URL parameters, empty by default.
            See Biolovision API documentation.

        Returns
        -------
        json : dict or None
            dict decoded from json if status OK, else None
        """
        opt_params = dict()
        for key, value in kwargs.items():
            opt_params[key] = value
        logger.debug(_("In api_list, with parameters %s"), opt_params)
        return super().api_list(opt_params)

    def api_diff(self, delta_time: str, modification_type: str = "all"):
        """Query for a list of updates or deletions since a given date.

        Calls /observations/diff to get list of created/updated or deleted
        observations since a given date (max 10 weeks backward).

        Parameters
        ----------
        id_taxo_group : str
            taxo group from which to query diff.
        delta_time : str
            Start of time interval to query.
        modification_type : str
            Type of diff queried : can be only_modified, only_deleted or
            all (default).

        Returns
        -------
        json : dict or None
            dict decoded from json if status OK, else None
        """
        # Mandatory parameters.
        params = {
            "user_email": self._config.user_email,
            "user_pw": self._config.user_pw,
        }
        # Specific parameters.
        params["modification_type"] = modification_type
        params["date"] = delta_time
        # GET from API
        return super()._url_get(params, "observations/diff/")

    def api_search(self, cfg, q_params, **kwargs):
        """Search for observations, based on parameter conditions.

        Calls /observations/search to get observations
        same parameters than in online version can be used

        Parameters
        ----------
        q_params : dict
            Query parameters, same as online version.
        **kwargs :
            optional URL parameters, empty by default.
            See Biolovision API documentation.

        Returns
        -------
        json : dict or None
            dict decoded from json if status OK, else None
        """
        # Mandatory parameters.
        params = {}
        for key, value in kwargs.items():
            params[key] = value
        # Specific parameters.
        if q_params is not None:
            body = json.dumps(q_params)
        else:
            raise IncorrectParameter
        logger.debug(
            _("Search from %s, with option %s and body %s"),
            self._ctrl,
            params,
            body,
        )
        # GET from API
        return super()._url_get(
            "exports/api/" + str(self._config.export_id), params, "GET", body
        )


class DatasetsAPI(GeoNatureAPI):
    """Jdd API"""