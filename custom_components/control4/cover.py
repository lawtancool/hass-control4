"""Platform for Control4 Covers (blinds/shades)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
	ATTR_POSITION,
	CoverEntity,
	CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pyControl4.blind import C4Blind

from . import Control4Entity
from .const import (
	CONF_DIRECTOR,
	CONF_DIRECTOR_ALL_ITEMS,
	CONTROL4_ENTITY_TYPE,
	DOMAIN,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

# Substrings commonly found in Control4 proxy identifiers for window coverings
_COVER_PROXY_SUBSTRINGS = {
	"shade",
	"blind",
	"windowcover",
	"curtain",
	"drap",
}

_POSITION_SUPPORTED_DEVICE_MODELS = {
	"qmotion": {
		"qadvanced roller shade",
	}
}


async def async_setup_entry(
	hass: HomeAssistant,
	entry: ConfigEntry,
	async_add_entities: AddEntitiesCallback,
) -> None:
	"""Set up Control4 covers from a config entry."""
	entry_data = hass.data[DOMAIN][entry.entry_id]
	all_items: list[dict[str, Any]] = entry_data[CONF_DIRECTOR_ALL_ITEMS]

	# Build quick lookup by id for parent data
	items_by_id = {item.get("id"): item for item in all_items if "id" in item}

	def _is_cover_proxy(proxy_value: str | None) -> bool:
		if not proxy_value or not isinstance(proxy_value, str):
			return False
		p = proxy_value.lower()
		return p in _COVER_PROXY_SUBSTRINGS

	def _supports_position(device_manufacturer: str | None, device_model: str | None) -> bool:
		if not device_model or not isinstance(device_model, str) or not device_manufacturer or not isinstance(device_manufacturer, str):
			return False
		k = device_manufacturer.lower()
		p = device_model.lower()
		return p in _POSITION_SUPPORTED_DEVICE_MODELS.get(k, {})

	# Identify cover entities via proxy type heuristics
	cover_items: list[dict[str, Any]] = [
		item
		for item in all_items
		if item.get("type") == CONTROL4_ENTITY_TYPE
		and item.get("id")
		and _is_cover_proxy(item.get("proxy"))
	]

	entity_list: list[Control4Cover] = []

	for item in cover_items:
		try:
			item_name = str(item["name"])
			item_id = item["id"]
			item_area = item.get("roomName")
			item_parent_id = item["parentId"]

			item_manufacturer = None
			item_device_name = None
			item_model = None
			is_positional = False

			parent = items_by_id.get(item_parent_id)
			if parent:
				item_manufacturer = parent.get("manufacturer")
				item_device_name = parent.get("name")
				item_model = parent.get("model")
				is_positional = _supports_position(item_manufacturer, item_model)
		except KeyError:
			_LOGGER.exception(
				"Unknown device properties received from Control4: %s",
				item,
			)
			continue

		item_attributes = await director_get_entry_variables(hass, entry, item_id)
		item_attributes["positional"] = is_positional

		entity_list.append(
			Control4Cover(
				entry_data,
				entry,
				item_name,
				item_id,
				item_device_name,
				item_manufacturer,
				item_model,
				item_parent_id,
				item_area,
				item_attributes,
			)
		)

	async_add_entities(entity_list, True)


class Control4Cover(Control4Entity, CoverEntity):  # type: ignore[misc]
	"""Control4 cover (blinds/shades) entity."""

	def __init__(
		self,
		*args
	) -> None:
		super().__init__(*args)
		self._is_positional = self._extra_state_attributes["positional"]
		if self._is_positional:
			self._attr_assumed_state = False
			self._attr_supported_features = (
				CoverEntityFeature.OPEN
				| CoverEntityFeature.CLOSE
				| CoverEntityFeature.STOP
				| CoverEntityFeature.SET_POSITION
			)
		else:
			self._attr_assumed_state = True
			self._attr_supported_features = (
				CoverEntityFeature.OPEN
				| CoverEntityFeature.CLOSE
				| CoverEntityFeature.STOP
			)

	def create_api_object(self) -> C4Blind:
		"""Create a pyControl4 device object.
		This exists so the director token used is always the latest one,
		without needing to re-init the entire entity.
		"""
		return C4Blind(self.entry_data[CONF_DIRECTOR], self._idx)

	async def async_added_to_hass(self):
		await super().async_added_to_hass()

	@property
	def current_cover_position(self) -> int | None:  # type: ignore[override]
		"""Get cover position."""
		if not self._is_positional:
			return None
		return self._extra_state_attributes["Level"]

	@property
	def is_closed(self) -> bool | None:  # type: ignore[override]
		"""Is cover closed."""
		if not self._is_positional:
			return None
		return self._extra_state_attributes["Fully Closed"]

	@property
	def is_closing(self) -> bool | None:  # type: ignore[override]
		"""Is cover closing."""
		if not self._is_positional:
			return None
		return self._extra_state_attributes["Closing"]

	@property
	def is_opening(self) -> bool | None:  # type: ignore[override]
		"""Is cover opening."""
		if not self._is_positional:
			return None
		return self._extra_state_attributes["Opening"]

	async def async_open_cover(self, **kwargs: Any) -> None:
		"""Open the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.open()

	async def async_close_cover(self, **kwargs: Any) -> None:
		"""Close the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.close()

	async def async_set_cover_position(self, **kwargs: Any) -> None:
		"""Set blind position."""
		if not self._is_positional:
			return None
		c4_blind = self.create_api_object()
		await c4_blind.set_level_target(level=kwargs.get(ATTR_POSITION))

	async def async_stop_cover(self, **kwargs: Any) -> None:
		"""Stop the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.stop()

	async def async_update(self) -> None:
		"""Get the cover state from the device"""
		if self._attr_assumed_state:
			return None
		director = self.entry_data[CONF_DIRECTOR]
		data = await director.get_item_variables(self._idx)
		for item in data:
			self._extra_state_attributes[item["varName"]] = item["value"]
