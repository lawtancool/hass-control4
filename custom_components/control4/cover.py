"""Platform for Control4 Covers (blinds/shades)."""
from __future__ import annotations

import logging
from typing import (
	Any,
	Callable
)

from homeassistant.components.cover import (
	ATTR_POSITION,
	CoverEntity,
	CoverEntityFeature,
	CoverDeviceClass,
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

_DEFAULT_SUPPORTED_FEATURES = (
    CoverEntityFeature.OPEN
	| CoverEntityFeature.CLOSE
	| CoverEntityFeature.STOP
)

class Control4CoverModel:  # type: ignore[misc]
	def __init__(
		self,
		cover_device_class: CoverDeviceClass | None = None,
		is_stateful: bool = False,
		fn_position: Callable[[dict[str, Any]], bool] | None = None,
		fn_is_closed: Callable[[dict[str, Any]], bool] | None = None,
		fn_is_closing: Callable[[dict[str, Any]], bool] | None = None,
		fn_is_opening: Callable[[dict[str, Any]], bool] | None = None,
		supported_features: CoverEntityFeature = _DEFAULT_SUPPORTED_FEATURES
	) -> None:
		self.cover_device_class = cover_device_class
		self.is_stateful = is_stateful if is_stateful is not None else False
		self.fn_get_position = fn_position
		self.fn_is_closed = fn_is_closed
		self.fn_is_closing = fn_is_closing
		self.fn_is_opening = fn_is_opening
		self.supported_features = supported_features

	def get_position(self, attributes: dict[str, Any]) -> bool | None:
		if self.fn_get_position is not None:
			return self.fn_get_position(attributes)

	def get_is_closed(self, attributes: dict[str, Any]) -> bool | None:
		if self.fn_is_closed is not None:
			return self.fn_is_closed(attributes)

	def get_is_closing(self, attributes: dict[str, Any]) -> bool | None:
		if self.fn_is_closing is not None:
			return self.fn_is_closing(attributes)

	def get_is_opening(self, attributes: dict[str, Any]) -> bool | None:
		if self.fn_is_opening is not None:
			return self.fn_is_opening(attributes)

# Manufacturers and models that support level positionnig
_KNOWN_COVER_MODELS = {
	"blind_qmotion_qadvanced_roller_shade.c4z": Control4CoverModel(
		cover_device_class	= CoverDeviceClass.SHADE,
		is_stateful 		= True,
		fn_get_position		= lambda attr: attr.get("Level"),
		fn_is_closed		= lambda attr: attr.get("Fully Closed"),
		fn_is_closing		= lambda attr: attr.get("Closing"),
		fn_is_opening		= lambda attr: attr.get("Opening"),
		supported_features	= _DEFAULT_SUPPORTED_FEATURES | CoverEntityFeature.SET_POSITION,
	),
	"gate_relay_control.c4z": Control4CoverModel(
		cover_device_class	= CoverDeviceClass.GATE,
		is_stateful			= True,
		fn_is_closed		= lambda attr: attr.get("STATE") == "Closed",
	),
}

_DEFAULT_COVER_MODEL = Control4CoverModel()

_MIN_COVER_LEVEL = 0
_MAX_COVER_LEVEL = 100

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

	def _get_cover_model(item: dict[str, Any]) -> Control4CoverModel | None:
		cover_model = _KNOWN_COVER_MODELS.get(item.get("protocolFilename"))
		if cover_model is not None:
			return cover_model
		# Identify cover entities via proxy type heuristics
		if _is_cover_proxy(item.get("proxy")):
			return _DEFAULT_COVER_MODEL
	
	entity_list: list[Control4Cover] = []

	for item in all_items:
		if item.get("type") != CONTROL4_ENTITY_TYPE or not item.get("id"):
			continue

		cover_model = _get_cover_model(item)
		if cover_model is None:
			continue

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
				cover_model,
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
        cover_model: Control4CoverModel,
        entry_data: dict,
        entry: ConfigEntry,
        name: str,
        idx: int,
        device_name: str | None,
        device_manufacturer: str | None,
        device_model: str | None,
        device_id: int,
        device_area: str | None,
        device_attributes: dict,
	) -> None:
		super().__init__(
			entry_data,
			entry,
			name,
			idx,
			device_name,
			device_manufacturer,
			device_model,
			device_id,
			device_area,
			device_attributes,
		)
		self._cover_model = cover_model
		self._attr_device_class = cover_model.cover_device_class
		self._attr_supported_features = self._cover_model.supported_features
		if self._cover_model.is_stateful:
			self._attr_should_poll = True
			self._attr_assumed_state = False
		else:
			self._attr_should_poll = False
			self._attr_assumed_state = True

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
		if not self._cover_model.is_stateful:
			return None
		p = self._cover_model.get_position(self._extra_state_attributes)
		if isinstance(p, str) and p.isdigit():
			p = int(p)
		if isinstance(p, int) and p >= _MIN_COVER_LEVEL and p <= _MAX_COVER_LEVEL:
			return p

	@property
	def is_closed(self) -> bool | None:  # type: ignore[override]
		"""Is cover closed."""
		if not self._cover_model.is_stateful:
			return None
		return self._cover_model.get_is_closed(self._extra_state_attributes)

	@property
	def is_closing(self) -> bool | None:  # type: ignore[override]
		"""Is cover closing."""
		if not self._cover_model.is_stateful:
			return None
		return self._cover_model.get_is_closing(self._extra_state_attributes)

	@property
	def is_opening(self) -> bool | None:  # type: ignore[override]
		"""Is cover opening."""
		if not self._cover_model.is_stateful:
			return None
		return self._cover_model.get_is_opening(self._extra_state_attributes)

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
		p = kwargs.get(ATTR_POSITION)
		if not isinstance(p, int):
			_LOGGER.exception("Invalid cover position given %s", p)
			return None
		p = max(_MIN_COVER_LEVEL, min(p, _MAX_COVER_LEVEL))
		c4_blind = self.create_api_object()
		await c4_blind.set_level_target(level=p)

	async def async_stop_cover(self, **kwargs: Any) -> None:
		"""Stop the cover."""
		c4_blind = self.create_api_object()
		await c4_blind.stop()

	async def async_update(self) -> None:
		"""Get the cover state from the device"""
		director = self.entry_data[CONF_DIRECTOR]
		data = await director.get_item_variables(self._idx)
		for item in data:
			self._extra_state_attributes[item["varName"]] = item["value"]
