"""Platform for Control4 Covers (blinds/shades and garage doors)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.cover import (
	CoverDeviceClass,
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
_COVER_PROXY_SUBSTRINGS = (
	"shade",
	"blind",
	"windowcover",
	"curtain",
	"drap",
)

_GARAGE_PARENT_TYPE = 6
_GARAGE_PROXY = "uibutton"
_GARAGE_PARENT_NAME = "relay garage door controller"
_GARAGE_PARENT_MODEL = "1-3 relays"
_GARAGE_STATE_VARIABLE = "STATE"


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
		return any(s in p for s in _COVER_PROXY_SUBSTRINGS)

	def _is_garage_parent(item: dict[str, Any]) -> bool:
		name = str(item.get("name", "")).lower()
		model = str(item.get("model", "")).lower()
		return (
			item.get("type") == _GARAGE_PARENT_TYPE
			and item.get("proxy") == _GARAGE_PROXY
			and _GARAGE_PARENT_NAME in name
			and _GARAGE_PARENT_MODEL in model
		)

	garage_parent_ids = {
		item["id"] for item in all_items if item.get("id") and _is_garage_parent(item)
	}

	# Identify cover entities via proxy type heuristics
	cover_items: list[dict[str, Any]] = [
		item
		for item in all_items
		if item.get("type") == CONTROL4_ENTITY_TYPE
		and item.get("id")
		and _is_cover_proxy(item.get("proxy"))
	]

	garage_items: list[dict[str, Any]] = [
		item
		for item in all_items
		if item.get("type") == CONTROL4_ENTITY_TYPE
		and item.get("id")
		and item.get("proxy") == _GARAGE_PROXY
		and item.get("parentId") in garage_parent_ids
	]

	entity_list: list[CoverEntity] = []

	for item in cover_items:
		try:
			item_name = str(item["name"])
			item_id = item["id"]
			item_area = item.get("roomName")
			item_parent_id = item["parentId"]

			item_manufacturer = None
			item_device_name = None
			item_model = None

			parent = items_by_id.get(item_parent_id)
			if parent:
				item_manufacturer = parent.get("manufacturer")
				item_device_name = parent.get("name")
				item_model = parent.get("model")
		except KeyError:
			_LOGGER.exception(
				"Unknown device properties received from Control4: %s",
				item,
			)
			continue

		item_attributes = await director_get_entry_variables(hass, entry, item_id)

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

	for item in garage_items:
		try:
			item_name = str(item["name"])
			item_id = item["id"]
			item_area = item.get("roomName")
			item_parent_id = item["parentId"]

			parent = items_by_id.get(item_parent_id, {})
			item_manufacturer = parent.get("manufacturer")
			item_device_name = item_name
			item_model = parent.get("model")
		except KeyError:
			_LOGGER.exception(
				"Unknown garage door properties received from Control4: %s",
				item,
			)
			continue

		item_attributes = await director_get_entry_variables(hass, entry, item_id)
		if _GARAGE_STATE_VARIABLE not in item_attributes:
			item_attributes.update(
				await director_get_entry_variables(hass, entry, item_parent_id)
			)

		entity_list.append(
			Control4GarageCover(
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
	_attr_assumed_state = True
	_attr_supported_features = (
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
		"""Unknown in stateless mode to keep both buttons enabled."""
		return None

	@property
	def is_closed(self) -> bool | None:  # type: ignore[override]
		"""Unknown in stateless mode to keep both buttons enabled."""
		return None

	async def async_open_cover(self, **kwargs: Any) -> None:
		"""Open the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.open()

	async def async_close_cover(self, **kwargs: Any) -> None:
		"""Close the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.close()

	async def async_set_cover_position(self, **kwargs: Any) -> None:
		"""No-op in stateless mode (no position slider)."""
		return

	async def async_stop_cover(self, **kwargs: Any) -> None:
		"""Stop the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.stop()


class Control4GarageCover(Control4Entity, CoverEntity):  # type: ignore[misc]
	"""Control4 garage door exposed through a uibutton relay driver."""
	_attr_device_class = CoverDeviceClass.GARAGE
	_attr_supported_features = (
		CoverEntityFeature.OPEN
		| CoverEntityFeature.CLOSE
		| CoverEntityFeature.STOP
	)

	@property
	def _garage_state(self) -> str:
		value = self._extra_state_attributes.get(_GARAGE_STATE_VARIABLE)
		if value is None:
			value = self._extra_state_attributes.get(_GARAGE_STATE_VARIABLE.lower())
		return str(value or "").strip().lower()

	@property
	def is_closed(self) -> bool | None:  # type: ignore[override]
		"""Return whether the garage door is closed."""
		state = self._garage_state
		if state in {"closed", "close"}:
			return True
		if state in {"open", "opened", "opening", "closing", "stopped", "partial"}:
			return False
		return None

	@property
	def is_opening(self) -> bool:  # type: ignore[override]
		"""Return whether the garage door is opening."""
		return self._garage_state == "opening"

	@property
	def is_closing(self) -> bool:  # type: ignore[override]
		"""Return whether the garage door is closing."""
		return self._garage_state == "closing"

	async def _send_garage_command(self, command: str) -> None:
		director = self.entry_data[CONF_DIRECTOR]
		await director.send_post_request(
			f"/api/v1/items/{self._device_id}/commands",
			command,
			{},
		)
		await asyncio.sleep(1)
		try:
			self._extra_state_attributes.update(
				await director_get_entry_variables(
					self.hass, self.entry, self._device_id
				)
			)
		except Exception as err:  # noqa: BLE001
			_LOGGER.debug("Unable to refresh Control4 garage state: %s", err)

	async def _data_to_extra_state_attributes(self, data) -> None:
		"""Load garage state from websocket update data."""
		if isinstance(data, dict):
			for key in (_GARAGE_STATE_VARIABLE, _GARAGE_STATE_VARIABLE.lower()):
				value = data.get(key)
				if isinstance(value, dict):
					for state_key in ("current_state", "value", "STATE", "state"):
						if state_key in value:
							self._extra_state_attributes[_GARAGE_STATE_VARIABLE] = value[
								state_key
							]
							break
				elif value is not None:
					self._extra_state_attributes[_GARAGE_STATE_VARIABLE] = value
		await super()._data_to_extra_state_attributes(data)

	async def async_open_cover(self, **kwargs: Any) -> None:
		"""Open the garage door."""
		await self._send_garage_command("OPEN")

	async def async_close_cover(self, **kwargs: Any) -> None:
		"""Close the garage door."""
		await self._send_garage_command("CLOSE")

	async def async_stop_cover(self, **kwargs: Any) -> None:
		"""Stop the garage door."""
		await self._send_garage_command("STOP")

