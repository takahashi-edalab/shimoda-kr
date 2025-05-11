from __future__ import annotations
from enum import Enum
from decimal import Decimal
from abc import ABC, abstractmethod
from dataclasses import dataclass
from intervaltree import Interval


class SpaceType(Enum):
    ABOVE = 1
    BELOW = 2


@dataclass(frozen=True, order=True)
class Space:
    type: SpaceType
    y_min: Decimal
    y_max: Decimal

    def dict(self) -> dict:
        return dict(x=str(self.x), y=str(self.y))

    @property
    def y_interval(self) -> Interval:
        return Interval(self.y_min, self.y_max, self)


@dataclass(frozen=True, order=True)
class Pin:
    x: Decimal
    y: Decimal

    def __repr__(self) -> str:
        return f"Pin: ({self.x}, {self.y})"

    def dict(self) -> dict:
        return dict(x=str(self.x), y=str(self.y))


# NOTE: 不要？
@dataclass
class ReservedArea:
    x_interval: Interval
    y_interval: Interval


class Allocatables(ABC):
    @property
    @abstractmethod
    def x_interval(self):
        pass

    @property
    @abstractmethod
    def width(self):
        pass

    @property
    @abstractmethod
    def upper_space(self):
        pass

    @property
    @abstractmethod
    def lower_space(self):
        pass


class Blockage(Allocatables):
    def __init__(
        self,
        x_min: Decimal,
        x_max: Decimal,
        y_min: Decimal,
        y_max: Decimal,
    ):
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max
        self._x_interval = Interval(x_min, x_max, self)
        self._y_interval = Interval(y_min, y_max, self)

    @property
    def x_interval(self) -> Interval:
        return self._x_interval

    @property
    def y_interval(self) -> Interval:
        return self._y_interval

    @property
    def width(self) -> Decimal:
        return self.y_max - self.y_min

    @property
    def upper_space(self) -> Decimal:
        return Decimal("0.0")

    @property
    def lower_space(self) -> Decimal:
        return Decimal("0.0")

    def __repr__(self):
        return (
            f"Blockage: Ix[{self.x_min}, {self.x_max}] Iy[{self.y_min}, {self.y_max}]"
        )


class ShieldType(str):
    """Manage the classification around shield types."""

    def __init__(self, name: str | None):
        if name is None:
            name = ""
        self.name = name

    def is_none(self) -> bool:
        return self.name == ""

    def is_group_shield(self) -> bool:
        return self.name.count("G") > 0


class Shield(Allocatables):

    def __init__(
        self,
        name: str,
        type: ShieldType,
        layer: int,
        x_min: Decimal,
        x_max: Decimal,
        width: Decimal,
        space: Decimal,
    ):
        self.name = name
        self.type = type
        self.layer = layer
        self.x_min = x_min
        self.x_max = x_max
        self._x_interval = Interval(x_min, x_max, self)
        self._width = width
        self._space = space

    @property
    def x_interval(self) -> Interval:
        return self._x_interval

    @property
    def width(self) -> Decimal:
        return self._width

    @property
    def upper_space(self) -> Decimal:
        return self._space

    @property
    def lower_space(self) -> Decimal:
        return self._space

    def extend(self, other_x_iv: Interval) -> Shield:
        # TODO: implement this
        raise NotImplementedError
        # return Shield(
        #     name=self.name,
        #     type=self.type,
        #     x_interval=Interval(
        #         min(self.x_interval.begin, other_x_iv.begin),
        #         max(self.x_interval.end, other_x_iv.end),
        #         self.x_interval.data,
        #     ),
        #     width=self.width,
        #     space=self.space,
        # )

    def __repr__(self) -> str:
        return f"Sield: {self.name}({self.type})"


class Allocatables(ABC):
    @property
    @abstractmethod
    def x_interval(self):
        pass

    @property
    @abstractmethod
    def width(self):
        pass

    @property
    @abstractmethod
    def upper_space(self):
        pass

    @property
    @abstractmethod
    def lower_space(self):
        pass


class WireAllocatables(Allocatables, ABC):
    @property
    @abstractmethod
    def pins(self) -> list[Pin]:
        pass

    @property
    def y_mid_upper(self) -> Decimal:
        n_pins = len(self.pins)
        sorted_pins = sorted(self.pins, key=lambda p: p.y)
        y_mid_up = 0
        if not n_pins % 2 == 0:
            bu = n_pins // 2 + 1
            m = sorted_pins[bu - 1]
            y_mid_up = m.y
        else:
            u = n_pins // 2 + 1
            upper_pin = sorted_pins[u - 1]
            y_mid_up = upper_pin.y
        return y_mid_up

    @property
    def y_mid_lower(self) -> Decimal:
        n_pins = len(self.pins)
        sorted_pins = sorted(self.pins, key=lambda p: p.y)
        y_mid_low = 0
        if not n_pins % 2 == 0:
            bu = n_pins // 2 + 1
            m = sorted_pins[bu - 1]
            y_mid_low = m.y
        else:
            b = n_pins // 2
            bottom_pin = sorted_pins[b - 1]
            y_mid_low = bottom_pin.y
        return y_mid_low

    @property
    def y_mid(self) -> Decimal:
        ym = (self.y_mid_lower + self.y_mid_upper) / 2
        return ym

    def vertical_wirelength(self, y: Decimal = None) -> Decimal:
        if y is None:
            y = self.y_mid

        ans = Decimal("0.0")
        for p in self.pins:
            ans += abs(p.y - y)
        return ans


class Net(WireAllocatables):

    def __init__(
        self,
        name: str,
        layer: int,
        width: Decimal,
        space: Decimal,
        x_min: Decimal = None,
        x_max: Decimal = None,
        pins: list[Pin] = None,
        shield_type: str = None,
        group_no: str = None,
    ):
        if x_min is None and x_max is None:
            assert pins is not None, "pins should be given..."
            x_min = min([p.x for p in pins])
            x_max = max([p.x for p in pins])
            if x_min == x_max:
                x_max += Decimal("0.0000001")

        self.name = name
        self.layer = layer
        self.shield_type = ShieldType(shield_type)
        self._width = width
        self._space = space
        self.x_min = x_min
        self.x_max = x_max
        self._x_interval = Interval(x_min, x_max, self)
        self._pins = pins
        self.group_no = group_no

    @classmethod
    def from_x_minmax(cls, name, width, space, x_min, x_max) -> Net:
        return Net(name, width, space, x_min, x_max)

    @classmethod
    def from_pins(cls, name, width, space, pins: list) -> Net:
        return Net(name, width, space, pins=pins)

    @property
    def x_interval(self) -> Interval:
        return self._x_interval

    @property
    def width(self) -> Decimal:
        return self._width

    @property
    def upper_space(self) -> Decimal:
        return self._space

    @property
    def lower_space(self) -> Decimal:
        return self._space

    @property
    def pins(self) -> list[Pin]:
        return self._pins

    @property
    def group_name(self) -> str:
        net_name = self.name
        if "_" in self.name:
            i = self.name.index("_")
            # NOTE: 0~3 までしかないから+2でOK
            net_name = self.name[: i + 2]
        elif "<" in self.name:
            i = self.name.index("<")
            net_name = self.name[:i]
        return net_name

    def require_shield(self) -> bool:
        return not self.shield_type.is_none()

    def __repr__(self) -> str:
        return f"{self.name}: [{self.x_min}, {self.x_max}]"


class Allocation(Allocatables):
    def __init__(self, data: Allocatables, offset: Decimal):
        self.data = data
        self.offset = offset
        self._x_interval = Interval(data.x_interval.begin, data.x_interval.end, self)

    @property
    def type(self) -> str:
        return self.data.__class__.__name__

    @property
    def x_interval(self) -> Interval:
        return self._x_interval

    @property
    def width(self) -> Decimal:
        return self.data.width

    @property
    def upper_space(self) -> Decimal:
        return self.data.upper_space

    @property
    def lower_space(self) -> Decimal:
        return self.data.lower_space

    @property
    def name(self) -> str:
        if isinstance(self.data, Net) or isinstance(self.data, Shield):
            return self.data.name
        elif isinstance(self.data, Blockage):
            return "Blockage"
        else:
            raise ValueError(f"Invalid data type: {type(self.data)}")

    @property
    def x_min(self) -> Decimal:
        return self.x_interval.begin

    @property
    def x_max(self) -> Decimal:
        return self.x_interval.end

    @property
    def y_min(self) -> Decimal:
        return self.offset

    @property
    def y_max(self) -> Decimal:
        return self.offset + self.data.width

    @property
    def y_max_with_space(self) -> Decimal:
        return self.offset + self.data.width + self.data.upper_space

    @property
    def y_interval(self) -> Interval:
        return Interval(self.offset, self.offset + self.width, self)

    def __repr__(self):
        return f"{type(self.data)}: [{self.offset},{self.offset+self.width}]"
