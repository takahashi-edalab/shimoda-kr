import os
import time
import argparse
from intervaltree import Interval
from gcr import entities, utils
from src import local_routing, global_routing, const


def remove_not_assumed_netlist(net_group_dict: dict, problem_settings: dict) -> dict:
    """想定していないnetlistを除去する

    Args:
        net_group_dict (dict): ネットグループ辞書
        problem_settings (dict): 問題設定クラス

    Returns:
        net_group_dict (dict): 要素が削除されたnet_group_dict
    """
    # 先に配線対象層以外を削除
    remove_net_group_name = []
    for net_group_name, nl in net_group_dict.items():
        if not nl[0].layer == problem_settings.target_layer:
            remove_net_group_name.append(net_group_name)

    for net_group_name in set(remove_net_group_name):
        del net_group_dict[net_group_name]

    remove_net_group_name = []
    for net_group_name, nl in net_group_dict.items():
        # 同じgroupで配線層が異なる
        if len(set([n.layer for n in nl])) != 1:
            remove_net_group_name.append(net_group_name)

    print("=" * 30)
    print("Remove net group due to not-compatible design rules: ")
    for net_group_name in set(remove_net_group_name):
        print(f"- {net_group_name}")
        del net_group_dict[net_group_name]
    print("=" * 30)
    return net_group_dict


def divide_nets_into_local_or_global(
    net_group_dict: dict, blockages_x_intervals: list[Interval]
) -> tuple[dict, dict]:
    """ネットをlocalとglobalに分ける

    Args:
        net_group_dict (dict): _description_
        blockages_x_intervals (list[Interval]): _description_

    Returns:
        tuple[dict, dict]: _description_
    """

    def overlap_blockage_x_interval(
        net: entities.Net, blockages_x_intervals: list[Interval]
    ) -> bool:
        for block_x_interval in blockages_x_intervals:
            if net.x_interval.overlaps(block_x_interval):
                return True
        return False

    global_net_group_dict = {}
    local_net_group_dict = {}
    for net_group_name, nl in net_group_dict.items():
        global_nl = []
        local_nl = []
        for n in nl:
            if overlap_blockage_x_interval(n, blockages_x_intervals):
                global_nl.append(n)
            else:
                local_nl.append(n)

        if global_nl != [] and local_nl != []:
            raise ValueError(
                f"Cross and Not-cross Net are in the same group..\n cross: {nl}\nnot cross: {local_nl}\n"
            )

        if global_nl != []:
            global_net_group_dict[net_group_name] = global_nl
        else:
            local_net_group_dict[net_group_name] = local_nl

    return global_net_group_dict, local_net_group_dict


def two_step_routing(netlist_dict: dict, problem_settings: dict) -> None:
    """2-stepで配線をする

    Args:
        netlist_dict (dict): _description_
        problem_settings (dict): _description_
    """

    # global/localで配線するnetlistを分ける
    global_net_group_dict, local_net_group_dict = divide_nets_into_local_or_global(
        netlist_dict, problem_settings.blockage_x_intervals
    )

    ##################################
    # local routing
    ##################################
    subchannels, unallocatable_local_net_group_dict = local_routing.run(
        local_net_group_dict, problem_settings
    )

    # 配線できなかったnetを global netlistに追加
    for net_group_name, nl in unallocatable_local_net_group_dict.items():
        assert (
            not net_group_name in global_net_group_dict
        ), "Net Group Name Duplication Error"
        global_net_group_dict[net_group_name] = nl

    ##################################
    # Global routing
    ##################################
    gaps = global_routing.run(global_net_group_dict, problem_settings)

    ##################################
    # Result Summary
    ##################################
    print("=" * 50)
    print("Routing Result Summary")
    # 使用RA数
    print("#RAs used")
    n_ra_used = utils.get_n_routing_areas_used(gaps)
    print(f"- #gaps: {n_ra_used}")
    for col, subc in subchannels.items():
        n_ra_used = utils.get_n_routing_areas_used(subc)
        print(f"- #subchannels-col{col}: {n_ra_used}")
    # 配線長
    print("Wirelength")
    twl = utils.total_vertical_wirelength(gaps)
    print(f"- gaps: {twl}")
    for col, subc in subchannels.items():
        twl = utils.total_vertical_wirelength(subc)
        print(f"- subchannels-col{col}: {twl}")
    print("=" * 50)

    # save routing result...
    if problem_settings.use_gco:
        prefix = f"{problem_settings.algorithm_name}_gco"
    else:
        prefix = f"{problem_settings.algorithm_name}"
    fname = prefix + f"_layer{problem_settings.target_layer}.json"
    utils.RoutingResultSerializer(problem_settings).serialize(
        fname, gaps=gaps, subchannels=subchannels
    )


def get_args():
    parser = argparse.ArgumentParser(description="Gap Channel Router")
    parser.add_argument(
        "--netlist",
        "-nl",
        default="assets/input/netlist.csv",
        help="Netlist file path",
    )
    parser.add_argument(
        "--problem_settings",
        "-ps",
        default="assets/input/problem_settings.yaml",
        help="Problem settings file path",
    )
    parser.add_argument(
        "--reserved_areas",
        "-ra",
        default="assets/input/reserved_areas.csv",
        help="Reserved area file path. Reserved area is area for circuit block.",
    )
    parser.add_argument(
        "--layer",
        "-l",
        choices=["D1", "D2"],
        default="D1",
        help="Routing layer to use",
    )
    parser.add_argument(
        "--algorithm",
        "-a",
        choices=["le", "cap", "ccap"],
        default="ccap",
        help="Algorithm to use",
    )
    parser.add_argument(
        "--gco",
        default=False,
        action="store_true",
        help="Whether to use GCO or not",
    )
    parser.add_argument(
        "--save_dir",
        "-sd",
        default="assets/output/",
        help="Save directory",
    )
    args = parser.parse_args()
    return args


def main():
    args = get_args()
    print(f"Target Layer: {args.layer}")
    print(f"Problem Settings: {os.path.basename(args.problem_settings)}")
    print(f"Netlist: {os.path.basename(args.netlist)}")
    print(f"Reserved Area: {os.path.basename(args.reserved_areas)}")
    print(f"Algorithm: {args.algorithm}")

    # 設定読み込み
    pb = utils.load_yaml(args.problem_settings)
    problem_settings = const.ProblemSettings(pb, args)
    # 入力読み込み
    net_group_dict: dict = utils.read_netlist_from_csv(args.netlist, problem_settings)
    # 想定していないnetlistを除去
    net_group_dict = remove_not_assumed_netlist(net_group_dict, problem_settings)
    # 配線開始
    start = time.time()
    two_step_routing(net_group_dict, problem_settings)
    print(f"Elapsed: {time.time() - start:.2f} [s]")


if __name__ == "__main__":
    main()
