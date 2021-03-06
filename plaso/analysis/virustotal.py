# -*- coding: utf-8 -*-
"""Look up files in VirusTotal and tag events derived from them."""

import logging
import sys

import requests

from plaso.analysis import interface
from plaso.analysis import manager
from plaso.lib import errors

class VirusTotalAnalyzer(interface.HashAnalyzer):
  """Class that analyzes file hashes by consulting VirusTotal."""
  _VIRUSTOTAL_API_REPORT_URL = (
      u'https://www.virustotal.com/vtapi/v2/file/report')


  def __init__(self, hash_queue, hash_analysis_queue, **kwargs):
    """Initializes a VirusTotal Analyzer thread.

    Args:
      hash_queue: A queue (instance of Queue.queue) that contains hashes to
                  be analyzed.
      hash_analysis_queue: A queue (instance of Queue.queue) that the analyzer
                           will append HashAnalysis objects to.
    """
    super(VirusTotalAnalyzer, self).__init__(
        hash_queue, hash_analysis_queue, **kwargs)
    self._api_key = None
    self._checked_for_old_python_version = False

  def SetAPIKey(self, api_key):
    """Sets the VirusTotal API key to use in queries.

    Args:
      _api_key: The VirusTotal API key
    """
    self._api_key = api_key

  def Analyze(self, hashes):
    """Looks up hashes in VirusTotal using the VirusTotal HTTP API.

    The API is documented here:
      https://www.virustotal.com/en/documentation/public-api/

    Args:
      hashes: A list of hashes (strings) to look up.

    Returns:
      A list of HashAnalysis objects.
    """
    if not self._api_key:
      raise RuntimeError(u'No API key specified for VirusTotal lookup.')

    hash_analyses = []
    try:
      json_response = self._GetVirusTotalJSONResponse(hashes)
    except errors.ConnectionError as exception:
      logging.error(
          u'Error communicating with VirusTotal {0:s}. VirusTotal plugin is '
          u'aborting.'.format(exception))
      self.SignalAbort()
      return hash_analyses
    # The content of the response from VirusTotal has a different structure if
    # one or more than once hash is looked up at once.
    if isinstance(json_response, dict):
      # Only one result.
      resource = json_response[u'resource']
      hash_analysis = interface.HashAnalysis(resource, json_response)
      hash_analyses.append(hash_analysis)
    else:
      for result in json_response:
        resource = result[u'resource']
        hash_analysis = interface.HashAnalysis(resource, result)
        hash_analyses.append(hash_analysis)
    return hash_analyses

  def _GetVirusTotalJSONResponse(self, hashes):
    """Makes a request to VirusTotal for information about hashes.

    Args:
      A list of file hashes (strings).

    Returns:
      The decoded JSON response from the VirusTotal API for the hashes.

    Raises:
      requests.ConnectionError: If it was not possible to connect to
                                VirusTotal.
      requests.exceptions.HTTPError: If the VirusTotal server returned an
                                     error code.
    """
    resource_string = u', '.join(hashes)
    params = {u'apikey': self._api_key, u'resource': resource_string}

    if not self._checked_for_old_python_version:
      if sys.version_info[0:3] < (2, 7, 9):
        logging.warn(
            u'You are running a version of Python prior to 2.7.9. Your version '
            u'of Python has multiple weaknesses in its SSL implementation that '
            u'can allow an attacker to read or modify SSL encrypted data. '
            u'Please update. Further SSL warnings will be suppressed. See '
            u'https://www.python.org/dev/peps/pep-0466/ for more information.')
        requests.packages.urllib3.disable_warnings()
      self._checked_for_old_python_version = True

    try:
      response = requests.get(self._VIRUSTOTAL_API_REPORT_URL, params=params)
      response.raise_for_status()
    except requests.ConnectionError as exception:
      error_string = u'Unable to connect to VirusTotal: {0:s}'.format(
          exception)
      raise errors.ConnectionError(error_string)
    except requests.HTTPError as exception:
      error_string = u'VirusTotal returned a HTTP error: {0:s}'.format(
          exception)
      raise errors.ConnectionError(error_string)
    json_response = response.json()
    return json_response


class VirusTotalAnalysisPlugin(interface.HashTaggingAnalysisPlugin):
  """An analysis plugin for looking up hashes in VirusTotal."""
  # VirusTotal allows lookups using any of these hash algorithms.
  REQUIRED_HASH_ATTRIBUTES = [u'sha256_hash', u'sha1_hash', u'md5_hash']

  # TODO: Check if there are other file types worth checking VirusTotal for.
  DATA_TYPES = [u'pe:compilation:compilation_time']

  URLS = [u'https://virustotal.com']

  NAME = u'virustotal'

  _VIRUSTOTAL_NOT_PRESENT_RESPONSE_CODE = 0
  _VIRUSTOTAL_PRESENT_RESPONSE_CODE = 1
  _VIRUSTOTAL_ANALYSIS_PENDING_RESPONSE_CODE = -2

  def __init__(self, event_queue):
    """Initializes a VirusTotal analysis plugin.

    Args:
      event_queue: A queue that is used to listen for incoming events.
    """
    super(VirusTotalAnalysisPlugin, self).__init__(
        event_queue, VirusTotalAnalyzer)
    self._api_key = None

  def SetAPIKey(self, api_key):
    """Sets the VirusTotal API key to use in queries.

    Args:
      _api_key: The VirusTotal API key
    """
    self._analyzer.SetAPIKey(api_key)

  def EnableFreeAPIKeyRateLimit(self, rate_limit):
    """Configures Rate limiting for queries to VirusTotal.

    The default rate limit for free VirusTotal API keys is 4 requests per
    minute.

    Args:
      rate_limit: Whether not to apply the free API key rate limit.
    """
    if rate_limit:
      self._analyzer.hashes_per_batch = 4
      self._analyzer.wait_after_analysis = 60
      self._analysis_queue_timeout = self._analyzer.wait_after_analysis + 1

  def GenerateTagString(self, hash_information):
    """Generates a string that will be used in the event tag.

    Args:
      hash_information: A dictionary containing the JSON decoded contents of the
                        result of a VirusTotal lookup, as produced by the
                        VirusTotalAnalyzer.
    """
    response_code = hash_information[u'response_code']
    if response_code == self._VIRUSTOTAL_NOT_PRESENT_RESPONSE_CODE:
      return u'Unknown to VirusTotal'
    elif response_code == self._VIRUSTOTAL_PRESENT_RESPONSE_CODE:
      positives = hash_information[u'positives']
      if positives > 0:
        return u'VirusTotal Detections {0:d}'.format(positives)
      return u'No VirusTotal Detections'
    elif response_code == self._VIRUSTOTAL_ANALYSIS_PENDING_RESPONSE_CODE:
      return u'VirusTotal Analysis Pending'
    else:
      logging.error(u'VirusTotal returned unknown response code '
                    u'{0!s}'.format(response_code))
      return u'VirusTotal Unknown Response code {0!s}'.format(response_code)


manager.AnalysisPluginManager.RegisterPlugin(VirusTotalAnalysisPlugin)
