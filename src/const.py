from decimal import Decimal
from intervaltree import Interval
from gcr import entities, containers, routing_area


class ProblemSettings:

    def __init__(self, pb: dict, args: dict):
        # file paths
        self.reserved_areas_file = args.reserved_areas
        self.algorithm_name = args.algorithm
        self.use_gco = args.gco

        # load arguments
        self.target_layer = args.layer
        self.save_dir = args.save_dir

        # load common parameters
        self.n_gaps = pb["num_gaps"]
        self.n_subchannels = pb["num_subchannels"]
        self.interval = pb["gap_y_interval"]
        self.y_bottom_blockage = pb["y_bottom_blockage"]

        self.avoid_points = {}
        for k, v in pb["avoid_points"].items():
            self.avoid_points[k] = entities.Pin(v["x"], v["y"])

        self.blockage_x_intervals = []
        for v in pb["blockage_x_intervals"]:
            self.blockage_x_intervals.append(Interval(v["x_min"], v["x_max"]))
        self.blockage_x_intervals = sorted(
            self.blockage_x_intervals, key=lambda x: x.begin
        )

        self.subchannel_x_intervals = []
        for v in pb["subchannel_x_intervals"]:
            self.subchannel_x_intervals.append(Interval(v["x_min"], v["x_max"]))
        self.subchannel_x_intervals = sorted(
            self.subchannel_x_intervals, key=lambda x: x.begin
        )

        # layer independent parameters
        self.gap_width_dict = pb["gap_width"]
        self.shield_width_dict = pb["shield_width"]
        self.subchannel_width_dict = pb["subchannel_width"]

        # fixed net info
        # NOTE: fix_net_group_dict[net_group_name][property_name] = fixed_parameter
        self.fix_net_group_dict = pb["fix_net_group"]

    @property
    def shield_width(self) -> Decimal:
        return self.shield_width_dict[self.target_layer]

    @property
    def gap_width(self) -> dict:
        return self.gap_width_dict[self.target_layer]

    @property
    def gap_interval(self) -> Decimal:
        return self.interval - self.gap_width_dict[self.target_layer]

    def gap_height(self, i: int) -> Decimal:
        return (
            self.y_bottom_blockage
            + Decimal(i + 1) * self.gap_interval
            + i * self.gap_width
        )

    def generate_gap(self) -> routing_area.RoutingArea:
        return routing_area.RoutingArea(width=self.gap_width)

    def generate_gaps(self) -> list[routing_area.RoutingArea]:
        gaps = []
        for i in range(self.n_gaps):
            g = routing_area.RoutingArea(i, self.gap_width, self.gap_height(i))
            gaps.append(g)
        return gaps

    @property
    def num_subchannel_cols(self) -> int:
        return len(self.subchannel_x_intervals)

    @property
    def subchannel_width(self) -> Decimal:
        return self.subchannel_width_dict[self.target_layer]

    @property
    def subchannel_interval(self) -> Decimal:
        return self.interval

    def subchannel_height(self, i: int) -> Decimal:
        return self.y_bottom_blockage + Decimal(i) * self.subchannel_interval

    def generate_subchannel(self) -> routing_area.RoutingArea:
        return routing_area.RoutingArea(width=self.subchannel_width)

    def generate_subchannels(self) -> list[routing_area.RoutingArea]:
        subchannels = []
        for i in range(self.n_subchannels):
            sgap = routing_area.RoutingArea(
                i, self.subchannel_width, self.subchannel_height(i)
            )
            subchannels.append(sgap)
        return subchannels

    def generate_overlapped_interval_dict(
        self, nl: list[entities.Net]
    ) -> containers.OverlappedIntervalDict:
        if nl == []:
            return containers.OverlappedIntervalDict("", [], self.shield_width)
        return containers.OverlappedIntervalDict(
            nl[0].group_name, nl, self.shield_width
        )

    def read_reserved_areas(self) -> list[object]:
        import csv
        from gcr.entities import ReservedArea

        # read from file...
        reserved_areas = []
        with open(self.reserved_areas_file, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                # row: list[str]
                layer = row[0]
                if layer != self.target_layer:
                    continue

                x_min, y_min, x_max, y_max = map(Decimal, row[1:])
                ra = ReservedArea(Interval(x_min, x_max), Interval(y_min, y_max))
                reserved_areas.append(ra)
        return reserved_areas
