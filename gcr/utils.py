import re
import csv
import json
import os
from decimal import Decimal
from datetime import datetime
from collections import defaultdict
from gcr import routing_area, entities


def get_str_datetime() -> str:
    """ファイル名として使用する日時を取得する.

    Returns:
        str: 日付時刻の文字列. 例: 2021-09-01_12-34-56
    """
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def get_n_routing_areas_used(routing_areas: list[routing_area.RoutingArea]) -> int:
    """障害物以外に配線されているRAの数を取得する

    Args:
        routing_areas (list[routing_area.RoutingArea]): _description_

    Returns:
        int: _description_
    """
    n_ras_used = 0
    for ra in routing_areas:
        if ra.allocations_without_blockage != []:
            n_ras_used += 1
    return n_ras_used


def lower_bound_vwl(igs: list) -> Decimal:
    # lower bound of wirelength
    lower_bound_wirelength = 0
    for ig in igs:
        lower_bound_wirelength += ig.vertical_wirelength()
    return lower_bound_wirelength


def calc_vertical_wirelength(ra: routing_area.RoutingArea) -> Decimal:
    """与えられた配線領域内に配線されたネットの垂直配線長の合計を計算する.

    Args:
        ra (routing_area.RoutingArea): 対象配線領域

    Returns:
        Decimal: 合計垂直配線長
    """
    twl = Decimal("0.0")
    for alc in ra.allocations:
        if not isinstance(alc.data, entities.Net):
            continue
        twl += alc.data.vertical_wirelength(ra.height + alc.offset)
    return twl


def total_vertical_wirelength(ras: list[routing_area.RoutingArea]) -> Decimal:
    """与えられた複数の配線領域内に配線されたネットの垂直配線長の合計を計算する.

    Args:
        ras (list[routing_area.RoutingArea]): 対象配線領域のリスト

    Returns:
        Decimal: 合計垂直配線長
    """
    twl = 0
    for ra in ras:
        twl += calc_vertical_wirelength(ra)
    return twl


class RoutingResultSerializer:

    def __init__(self, problem_settings):
        self.problem_settings = problem_settings

    def convert_allocation_to_json(self, alc: entities.Allocation) -> dict:
        return {
            "name": alc.name,
            "type": alc.type,
            "x_interval": {
                "min": alc.x_min,
                "max": alc.x_max,
            },
            "y_interval": {
                "min": alc.y_min,
                "max": alc.y_max,
            },
        }

    def __serialize_gap_allocation(
        self, json_contents: dict, gaps: list[routing_area.RoutingArea]
    ) -> None:
        # gap, id, allocations
        json_contents["gaps"] = defaultdict(list)
        for g in gaps:
            for a in g.allocations:
                aj = self.convert_allocation_to_json(a)
                if type(aj) == list:
                    pass
                else:
                    json_contents["gaps"][g.id].append(aj)

    def __serialize_subchannel_allocation(
        self, json_contents: dict, subchannels_dict: dict
    ) -> None:
        # subchannel, col, id, allocations
        json_contents["subchannel"] = {}
        for col, subchannels in subchannels_dict.items():
            json_contents["subchannel"][col] = defaultdict(list)
            for subchannel in subchannels:
                for a in subchannel.allocations:
                    aj = self.convert_allocation_to_json(a)
                    json_contents["subchannel"][col][subchannel.id].append(aj)

    def serialize(
        self, fname: str, gaps: list = None, subchannels: dict = None
    ) -> None:
        assert not (gaps is None and subchannels is None)
        fsavepath = os.path.join(self.problem_settings.save_dir, fname)
        json_contents = {}
        if gaps is not None:
            self.__serialize_gap_allocation(json_contents, gaps)
        if subchannels is not None:
            self.__serialize_subchannel_allocation(json_contents, subchannels)

        self.save_json(fsavepath, json_contents)

    def save_json(self, save_path: str, contents: list) -> None:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        def decimal_to_str(obj):
            if isinstance(obj, Decimal):
                return str(obj)

        with open(save_path, "w") as f:
            json.dump(contents, f, indent=2, default=decimal_to_str)


class RoutingResultDeserializer:

    def __init__(self, problem_settings):
        self.problem_settings = problem_settings

    def deserialize(self, fname: str) -> dict:
        fsavepath = os.path.join(self.problem_settings.save_dir, fname)
        with open(fsavepath, "r") as f:
            allocations = json.load(f)
        return allocations


def load_yaml(fpath: str) -> dict:
    """yamlファイルを読み込む.

    Args:
        fpath (str): 読み込むyamlファイルのパス

    Returns:
        dict: yamlファイルの内容
    """
    import yaml
    from decimal import Decimal
    from yaml.loader import SafeLoader

    def decimal_constructor(loader, node):
        value = loader.construct_scalar(node)
        return Decimal(value)

    yaml.add_constructor(
        "tag:yaml.org,2002:float", decimal_constructor, Loader=SafeLoader
    )
    with open(fpath, "r") as file:
        data = yaml.safe_load(file)
    return data


def fix_net_parameters(net_group_dict: dict, problem_settings) -> dict:
    """一部のネットの情報を修正する

    Args:
        net_group_dict (dict): _description_
        problem_settings (_type_): _description_

    Returns:
        dict: _description_
    """
    fixed_net_group_dict = defaultdict(list)
    for net_group_name, org_nl in net_group_dict.items():
        if net_group_name in problem_settings.fix_net_group_dict:
            # 対象ネットはパラメータ修正
            new_nl = []
            for n in org_nl:
                new_n = entities.Net(
                    name=n.name,
                    layer=n.layer,
                    width=n.width,
                    space=problem_settings.fix_net_group_dict[net_group_name]["space"],
                    pins=n.pins,
                    shield_type=n.shield_type,
                    group_no=n.group_no,
                )
                new_nl.append(new_n)
        else:
            new_nl = org_nl

        fixed_net_group_dict[net_group_name] = new_nl
    return fixed_net_group_dict


def read_netlist_from_csv(fpath: str, problem_settings) -> dict:
    netlist = []
    net_group_dict = defaultdict(list)
    n_nets = defaultdict(int)
    with open(fpath, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            # row: list[str]
            name = row[0]

            # 上に逃げる配線: _*
            avoid_block_no = None
            pattern = r"_(\d+)"
            m = re.search(pattern, name)
            if m:
                avoid_block_no = m.group(1)

            # 束配線: <>
            group_no = None
            pattern = r"<(\d+)>"
            m = re.search(pattern, name)
            if m:
                group_no = m.group(1)

            layer = row[1]
            net_width = Decimal(row[2])
            net_space = Decimal(row[3])
            shield_type = row[4]
            pins_coord = row[5:]
            pin_names = pins_coord[0::3]
            px = pins_coord[1::3]
            py = pins_coord[2::3]
            pins = [
                entities.Pin(Decimal(x), Decimal(y)) for x, y in zip(px, py) if x != ""
            ]
            # 追加の逃げるpin
            if avoid_block_no:
                add_pin = problem_settings.avoid_points[avoid_block_no]
                pins.append(add_pin)

            net = entities.Net(
                name=name,
                layer=layer,
                width=net_width,
                space=net_space,
                pins=pins,
                shield_type=shield_type,
                group_no=group_no,
            )
            netlist.append(net)
            net_group_dict[net.group_name].append(net)
            # statas
            n_nets[layer] += 1

    new_dict = fix_net_parameters(net_group_dict, problem_settings)
    return new_dict
