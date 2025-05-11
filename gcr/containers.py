from abc import ABC, abstractmethod
import numpy as np
from collections import UserDict, UserList
from intervaltree import Interval, IntervalTree
from decimal import Decimal
from gcr import entities


class BaseContainer(entities.WireAllocatables, ABC):
    """_summary_

    Args:
        entities (_type_): _description_
        ABC (_type_): _description_

    Raises:
        AttributeError: _description_

    Returns:
        _type_: _description_
    """

    @property
    @abstractmethod
    def total_netlist(self) -> list[entities.Allocatables]:
        pass

    def total_width(self, nl: list[entities.Allocatables]) -> Decimal:
        total = 0
        total += sum([n.width for n in nl])
        for i in range(len(nl) - 1):
            total += max(nl[i].upper_space, nl[i + 1].lower_space)
        return total

    @property
    def width(self):
        w = self.total_width(self.total_netlist)
        return w

    @property
    def width_with_space(self) -> Decimal:
        wws = self.width + self.upper_space + self.lower_space
        return wws

    @property
    def upper_space(self) -> Decimal:
        return self.total_netlist[-1].upper_space

    @property
    def lower_space(self) -> Decimal:
        return self.total_netlist[0].lower_space

    @property
    def pins(self) -> list[entities.Pin]:
        _pins = []
        for n in self.total_netlist:
            if isinstance(n, entities.Net):
                _pins += n.pins
        return _pins


class ShieldedNetList(UserList, BaseContainer):
    """
    以下使用条件
    - 互いがx軸において重なるネットリスト
        - 与えられるx_ivは全てのネットを包含する範囲
            - シールド線は, x_ivの長さで挿入
            -> 一部のネットより長めに挿入される可能性
    - 全ネットのshield typeは一つ
    - 全ネットはまとめて一つのgapに配線可能

    """

    def __init__(self, netlist: list, x_interval: Interval, shield_width: Decimal):
        self.data = []
        if netlist == []:
            return

        self.__validation(netlist)

        #
        self.netlist = netlist
        self._x_interval = x_interval
        self.shield_width = shield_width
        #
        n = netlist[0]
        self.layer = n.layer
        self.group_name = n.group_name
        self.shield_type = n.shield_type
        self._is_group_net = self.shield_type.is_group_shield()
        # build
        if not n.require_shield():
            self.data = netlist
        elif self.shield_type.is_group_shield():
            self.__build_netlist_with_group_shield(netlist)
        else:
            self.__build_netlist_with_shield(netlist)

    @property
    def is_group_net(self) -> bool:
        return self._is_group_net

    def __validation(self, netlist: list) -> None:
        # # 現時点ではspaceは一つのみ.
        # assert (
        #     len(np.unique([n.space for n in netlist])) == 1
        # ), "Support only 1 unique space..."

        # 現時点ではshield typeは一つのみ.
        assert (
            len(np.unique([n.shield_type for n in netlist])) == 1
        ), "Support only 1 unique shield type..."

        pass

    def __build_netlist_with_shield(self, netlist: list):
        # add normal shield
        for i, n in enumerate(netlist):
            if i == 0:
                space = netlist[0].lower_space
            else:
                space = max(netlist[i - 1].upper_space, netlist[i].lower_space)

            iv_begin = max(netlist[i - 1].x_interval.begin, netlist[i].x_interval.begin)
            iv_end = max(netlist[i - 1].x_interval.end, netlist[i].x_interval.end)

            s = entities.Shield(
                f"{self.group_name}-shield",
                self.shield_type,
                self.layer,
                iv_begin,
                iv_end,
                self.shield_width,
                space,
            )
            self.data.append(s)
            self.data.append(n)

        s = entities.Shield(
            f"{self.group_name}-shield",
            self.shield_type,
            self.layer,
            netlist[-1].x_interval.begin,
            netlist[-1].x_interval.end,
            self.shield_width,
            netlist[-1].upper_space,
        )
        self.data.append(s)

    def __build_netlist_with_group_shield(self, netlist: list):
        s_bottom = entities.Shield(
            f"{self.group_name}-shield",
            self.shield_type,
            self.layer,
            self.x_interval.begin,
            self.x_interval.end,
            self.shield_width,
            netlist[0].lower_space,
        )
        s_top = entities.Shield(
            f"{self.group_name}-shield",
            self.shield_type,
            self.layer,
            self.x_interval.begin,
            self.x_interval.end,
            self.shield_width,
            netlist[-1].upper_space,
        )
        self.data = [s_bottom] + netlist + [s_top]

    @property
    def x_interval(self) -> Interval:
        return self._x_interval

    @property
    def total_netlist(self) -> list[entities.Allocatables]:
        # TODO: 配線順序を最適化
        # e.g., spaceが大きいもの同士を隣接させる
        return self.data

    def __add__(self, other):
        if isinstance(other, ShieldedNetList):
            return self.data + other.data
        elif isinstance(other, list):
            return self.data + other
        else:
            raise ValueError

    def __radd__(self, other):
        if isinstance(other, ShieldedNetList):
            return self.data + other.data
        elif isinstance(other, list):
            return self.data + other
        else:
            raise ValueError

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.data[index]
        return super().__getitem__(index)


class ShieldDict(UserDict, BaseContainer):
    """

    Args:
        UserDict (_type_): _description_
        BaseContainer (_type_): _description_
    """

    def __init__(self, netlist: list, x_interval: Interval, shield_width: Decimal):
        super().__init__()
        self._x_interval = x_interval
        shield_group = self.divide_netlist_by_shield_type(netlist)
        for shield_type, nl in shield_group.items():
            self.data[shield_type] = ShieldedNetList(nl, x_interval, shield_width)

    def divide_netlist_by_shield_type(self, nl: list) -> dict:
        grouping = {}
        for n in nl:
            if not n.shield_type in grouping:
                grouping[n.shield_type] = []
            grouping[n.shield_type].append(n)
        return grouping

    @property
    def x_interval(self) -> Interval:
        return self._x_interval

    @property
    def total_netlist(self) -> list[entities.Allocatables]:
        # NOTE & TODO: 配置順序で結合する
        # 現状, 何も考えていない.
        total_nl = []
        for nl in self.data.values():
            total_nl += nl
        return total_nl


class OverlappedIntervalDict(UserDict, BaseContainer):
    """_summary_

    Args:
        UserDict (_type_): _description_
        BaseContainer (_type_): _description_
    """

    def __init__(self, net_group_name: str, netlist: list, shield_width: Decimal):
        super().__init__()
        self.name = net_group_name
        # self.dist_priority = 0
        # self.layer = netlist[0].layer
        nldict_by_same_interval = self.grouping_by_same_interval(netlist)
        distinct_intervals = list(nldict_by_same_interval.keys())
        merged_intervals = self.merge_intervals(distinct_intervals)

        # initialize
        overlapped_nl_dict = {}
        for merged_iv in merged_intervals:
            overlapped_nl_dict[merged_iv] = []
        # collect netlist
        for iv, nl in nldict_by_same_interval.items():
            for merged_iv in merged_intervals:
                if merged_iv.overlaps(iv):
                    overlapped_nl_dict[merged_iv] += nl
                    break

        # each netlist is stored via snld
        for x_interval, nl in overlapped_nl_dict.items():
            snld = ShieldDict(nl, x_interval, shield_width)
            self.data[x_interval] = snld

    def grouping_by_same_interval(self, netlist: list) -> dict:
        d = {}
        for n in netlist:
            if not n.x_interval in d:
                d[n.x_interval] = []
            d[n.x_interval].append(n)
        return d

    def merge_intervals(self, ivs: list[Interval]) -> list[Interval]:
        if not ivs:
            return []

        merged = []
        ivs.sort(key=lambda z: z.begin)
        current_iv = ivs[0]
        for iv in ivs[1:]:
            if current_iv.overlaps(iv):
                current_iv = Interval(current_iv.begin, max(current_iv.end, iv.end))
                continue

            merged.append(current_iv)
            current_iv = iv

        merged.append(current_iv)
        return merged

    @property
    def x_interval(self) -> Interval:
        ivt = IntervalTree([n.x_interval for n in self.total_netlist])
        return Interval(ivt.begin(), ivt.end())

    @property
    def total_netlist(self):
        # NOTE: 合計pin-listや配線長でのみ使用
        total_nl = []
        for snld in self.data.values():
            total_nl += snld.total_netlist
        return total_nl

    @property
    def width(self) -> Decimal:
        w = max([v.width for v in self.data.values()])
        return w

    @property
    def width_with_space(self) -> Decimal:
        wws = max([v.width_with_space for v in self.data.values()])
        return wws

    @property
    def upper_space(self) -> Decimal:
        if len(self.data) > 1:
            return (self.width_with_space - self.width) / 2
        return self.total_netlist[-1].upper_space

    @property
    def lower_space(self) -> Decimal:
        if len(self.data) > 1:
            return (self.width_with_space - self.width) / 2
        return self.total_netlist[0].lower_space


class Bundle(UserList, BaseContainer):
    """事前配線ネットリストを束ねるクラス

    Args:
        UserList (_type_): _description_
        BaseContainer (_type_): _description_
    """

    def __init__(self, net_group_name: str, oids: list[OverlappedIntervalDict]):
        self.name = net_group_name
        self.data = oids

    @property
    def total_netlist(self) -> list[entities.Allocatables]:
        total_nl = []
        for d in self.data:
            total_nl += d.total_netlist
        return total_nl

    @property
    def x_interval(self) -> Interval:
        raise NotImplementedError

    def vertical_wirelength_with_multi_y(self, heights: list[Decimal] = None):
        assert len(heights) == len(self.data)
        total_vwl = Decimal("0")
        for h, ig in zip(heights, self.data):
            total_vwl += ig.vertical_wirelength(h)
        return total_vwl
