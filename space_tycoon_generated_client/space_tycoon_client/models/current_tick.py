# coding: utf-8

"""
    Space Tycoon

    Space Tycoon server.  # noqa: E501

    OpenAPI spec version: 1.0.0
    
    Generated by: https://github.com/swagger-api/swagger-codegen.git
"""

import pprint
import re  # noqa: F401

import six

class CurrentTick(object):
    """NOTE: This class is auto generated by the swagger code generator program.

    Do not edit the class manually.
    """
    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'tick': 'int',
        'min_time_left_ms': 'int',
        'season': 'int'
    }

    attribute_map = {
        'tick': 'tick',
        'min_time_left_ms': 'minTimeLeftMs',
        'season': 'season'
    }

    def __init__(self, tick=None, min_time_left_ms=None, season=None):  # noqa: E501
        """CurrentTick - a model defined in Swagger"""  # noqa: E501
        self._tick = None
        self._min_time_left_ms = None
        self._season = None
        self.discriminator = None
        self.tick = tick
        self.min_time_left_ms = min_time_left_ms
        self.season = season

    @property
    def tick(self):
        """Gets the tick of this CurrentTick.  # noqa: E501


        :return: The tick of this CurrentTick.  # noqa: E501
        :rtype: int
        """
        return self._tick

    @tick.setter
    def tick(self, tick):
        """Sets the tick of this CurrentTick.


        :param tick: The tick of this CurrentTick.  # noqa: E501
        :type: int
        """
        if tick is None:
            raise ValueError("Invalid value for `tick`, must not be `None`")  # noqa: E501

        self._tick = tick

    @property
    def min_time_left_ms(self):
        """Gets the min_time_left_ms of this CurrentTick.  # noqa: E501


        :return: The min_time_left_ms of this CurrentTick.  # noqa: E501
        :rtype: int
        """
        return self._min_time_left_ms

    @min_time_left_ms.setter
    def min_time_left_ms(self, min_time_left_ms):
        """Sets the min_time_left_ms of this CurrentTick.


        :param min_time_left_ms: The min_time_left_ms of this CurrentTick.  # noqa: E501
        :type: int
        """
        if min_time_left_ms is None:
            raise ValueError("Invalid value for `min_time_left_ms`, must not be `None`")  # noqa: E501

        self._min_time_left_ms = min_time_left_ms

    @property
    def season(self):
        """Gets the season of this CurrentTick.  # noqa: E501


        :return: The season of this CurrentTick.  # noqa: E501
        :rtype: int
        """
        return self._season

    @season.setter
    def season(self, season):
        """Sets the season of this CurrentTick.


        :param season: The season of this CurrentTick.  # noqa: E501
        :type: int
        """
        if season is None:
            raise ValueError("Invalid value for `season`, must not be `None`")  # noqa: E501

        self._season = season

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in six.iteritems(self.swagger_types):
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value
        if issubclass(CurrentTick, dict):
            for key, value in self.items():
                result[key] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, CurrentTick):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other
