from decimal import Decimal
from intervaltree import Interval, IntervalTree
from gcr import entities, containers


class RoutingArea:
    def __init__(
        self,
        id: int = None,
        width: Decimal = Decimal("inf"),
        height: Decimal = None,
    ) -> None:
        self.id = id
        self.width = width
        self.height = height
        self.x_iv_tree = IntervalTree()
        # NOTE: 予約領域による初期天井を記録
        self.init_ceilings = []

    @property
    def y_mid(self) -> Decimal:
        return self.height + self.width / 2

    @property
    def allocations(self) -> list[entities.Allocation]:
        alcs = []
        for iv in self.x_iv_tree:
            a = iv.data
            if isinstance(a.data, containers.ShieldedNetList):
                bundled_allocation = a.data
                offset = a.offset
                # 一番下の要素をそのままついか
                obj = bundled_allocation[0]
                alc = entities.Allocation(obj, offset)
                alcs.append(alc)
                # その上の要素を追加するのに必要な情報をとる(offset計算)
                width = obj.width
                upper_space_of_bottom_obj = obj.upper_space
                for o in bundled_allocation[1:]:
                    offset += width + max(upper_space_of_bottom_obj, o.lower_space)
                    alc = entities.Allocation(o, offset)
                    alcs.append(alc)
                    width = o.width
                    upper_space_of_bottom_obj = o.upper_space
            else:
                alcs.append(a)
        return alcs

    @property
    def allocations_without_blockage(self) -> list[entities.Allocation]:
        return [a for a in self.allocations if not isinstance(a, entities.Blockage)]

    def __repr__(self) -> str:
        return self.x_iv_tree.print_structure(tostring=True)

    def x_overlapped_allocations(self, x_iv: Interval) -> list[entities.Allocation]:
        ivs = self.x_iv_tree.overlap(x_iv)
        allocs = [iv.data for iv in ivs]
        return allocs

    def build_y_intervaltree(
        self, allocs: list[entities.Allocation], include_space: bool = False
    ) -> IntervalTree:
        y_iv_tree = IntervalTree()
        for a in allocs:
            # print(a.name)
            # print(a.width)
            y_iv_tree.add(a.y_interval)

            if include_space:
                if a.lower_space > Decimal("0.0"):
                    sb = entities.Space(
                        entities.SpaceType.BELOW,
                        a.offset - a.lower_space,
                        a.offset,
                    )
                    y_iv_tree.add(sb.y_interval)

                if a.upper_space > Decimal("0.0"):
                    sa = entities.Space(
                        entities.SpaceType.ABOVE,
                        a.y_max_with_space - a.upper_space,
                        a.y_max_with_space,
                    )
                    y_iv_tree.add(sa.y_interval)
        return y_iv_tree

    def y_max_space_min(
        self, allocs: list[entities.Allocation]
    ) -> tuple[Decimal, Decimal]:
        if allocs == []:
            return Decimal(0), Decimal(0)

        y_max = max([a.y_max_with_space for a in allocs])
        space_min = Decimal("inf")
        for a in allocs:
            if a.y_max_with_space == y_max and a.upper_space < space_min:
                space_min = a.upper_space
        return y_max, space_min

    def get_ceiling_space(
        self, ceiling: Decimal, x_iv: Interval = None
    ) -> Decimal | None:
        """If invalid ceiling is given, return None"""
        # get allocations overlapped given trunk in x-axis
        x_overlapped_allocs: list = self.x_overlapped_allocations(x_iv)
        # build space y_iv_tree
        space_y_iv_tree = self.build_y_intervaltree(
            x_overlapped_allocs, include_space=True
        )
        # get space set overlapped with given ceiling
        overlapped_spaces = space_y_iv_tree.at(ceiling)
        # if ceiling is inside interval of ABOVE space,
        # then ceiling is invalid ...
        ceiling_space = Decimal("0.0")
        for osp in list(overlapped_spaces):
            if not isinstance(osp.data, entities.Space):
                if not osp.begin == ceiling:
                    return None
            else:
                if osp.data.type == entities.SpaceType.ABOVE:
                    return None

            ceiling_space = max(ceiling_space, ceiling - osp.begin)
        return ceiling_space

    def get_offset(
        self, alc: entities.Allocatables, ceiling: Decimal = None
    ) -> Decimal | None:
        """If not allocatable, return None."""
        # ceilingがない場合: ceiling = w(g)
        if ceiling is None:
            ceiling = self.width

        # get allocations overlapped given trunk in x-axis
        x_overlapped_allocs: list = self.x_overlapped_allocations(alc.x_interval)
        # build y-axis intervaltree
        y_iv_tree = self.build_y_intervaltree(x_overlapped_allocs)

        # if ceiling_space is invalid, return None...
        ceiling_space = self.get_ceiling_space(ceiling, alc.x_interval)
        if ceiling_space is None:
            return None

        # NOTE: ここから下は, ceilingがvalidな条件...
        # below ceiling..
        y_ivs_below_ceiling = y_iv_tree.overlap(Decimal(0), ceiling) - y_iv_tree.at(
            ceiling
        )
        allocs_below_ceiling = [iv.data for iv in y_ivs_below_ceiling]
        y_max, space_min = self.y_max_space_min(allocs_below_ceiling)
        offset = y_max - space_min + max(space_min, alc.lower_space)

        # allocatable check
        if offset + alc.width + max(alc.upper_space, ceiling_space) > ceiling:
            return None
        return offset

    def allocatable(self, alc: entities.Allocatables, ceiling: Decimal = None) -> bool:
        if self.get_offset(alc, ceiling) is None:
            return False
        return True

    def __allocate(self, o: entities.Allocatables, offset: Decimal) -> Decimal:
        a = entities.Allocation(o, offset)
        self.x_iv_tree.add(a.x_interval)
        return a.y_max_with_space

    def __allocate_blockage(self, b: entities.Blockage) -> Decimal:
        # validate
        x_overlapped_allocs: list = self.x_overlapped_allocations(b.x_interval)
        y_iv_tree = self.build_y_intervaltree(x_overlapped_allocs)
        if y_iv_tree.overlap(b.y_min, b.y_max) != set():
            raise ValueError(f"Cannot allocate blockage {b}...")
        # allocate
        return self.__allocate(b, b.y_min)

    def __allocate_net(self, n: entities.Net, ceiling: Decimal = None) -> Decimal:
        # validate allocation
        offset = self.get_offset(n, ceiling)
        if offset is None:
            raise ValueError(f"Cannot allocate {n} from ceiling {ceiling}...")
        # allocate
        return self.__allocate(n, offset)

    def __allocate_shield(self, s: entities.Shield, ceiling: Decimal = None) -> Decimal:
        # TODO: fix me if yhou need shield-sharing...
        return self.__allocate_net(s, ceiling)

    def __allocate_netlist(
        self, snl: containers.ShieldedNetList, ceiling: Decimal = None
    ) -> Decimal:
        y_max = None
        for o in snl:
            if isinstance(o, entities.Net):
                y_max = self.__allocate_net(o, ceiling)
            elif isinstance(o, entities.Shield):
                y_max = self.__allocate_shield(o, ceiling)
            else:
                raise ValueError(
                    f"Invalid value is given. {o} should be Net or Shield."
                )
        return y_max

    def __allocate_shielddict(
        self, sd: containers.ShieldDict, ceiling: Decimal = None
    ) -> Decimal:
        y_maxs = []
        for shield_name, snl in sd.items():
            if snl.is_group_net:
                y_max = self.__allocate_net(snl, ceiling)
            else:
                y_max = self.__allocate_netlist(snl, ceiling)
            y_maxs.append(y_max)
        return max(y_maxs)

    def __allocate_overlappedintervaldict(
        self, oid: containers.OverlappedIntervalDict, ceiling: Decimal
    ) -> Decimal:
        y_maxs = []
        for interval, shielddict in oid.items():
            y_max = self.__allocate_shielddict(shielddict, ceiling)
            y_maxs.append(y_max)
        return max(y_maxs)

    def allocate(self, o: entities.Allocatables, ceiling: Decimal = None) -> Decimal:
        # TODO: fix me to add validation...
        # print(type(o))
        # print(isinstance(o, entities.Allocatables))
        # print(issubclass(type(o), entities.Allocatables))
        # assert isinstance(o, entities.Allocatables), "Invalid value is given..."

        # entities
        if isinstance(o, entities.Blockage):
            # NOTE: 予約領域の上下辺の高さを記録
            self.init_ceilings.append(o.y_min)
            self.init_ceilings.append(o.y_max)
            return self.__allocate_blockage(o)
        elif isinstance(o, entities.Net):
            return self.__allocate_net(o, ceiling)
        elif isinstance(o, entities.Shield):
            return self.__allocate_shield(o, ceiling)
        # containers
        elif isinstance(o, list) or isinstance(o, containers.ShieldedNetList):
            return self.__allocate_netlist(o, ceiling)
        elif isinstance(o, containers.ShieldDict):
            return self.__allocate_shielddict(o, ceiling)
        elif isinstance(o, containers.OverlappedIntervalDict):
            return self.__allocate_overlappedintervaldict(o, ceiling)
        else:
            raise ValueError(f"Invalid value is given. {o} should be Net or Shield.")
