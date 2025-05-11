from decimal import Decimal
from intervaltree import Interval
from collections import defaultdict
from gcr import entities, utils
from src import algorithms, preprocessing


def divide_nets_by_block(
    net_group_dict: dict, problem_settings: dict
) -> dict[dict[str, list]]:
    """block毎にnetlistを分ける

    Args:
        net_group_dict (dict): _description_
        problem_settings (dict): _description_

    Returns:
        dict[dict[str, list]]: _description_
    """
    # それぞれのcolに対応するnetlist-dict
    col2ent_group_dict = defaultdict(dict)
    # それぞれのcolに配線するネット数
    n_nets_in_areas = defaultdict(int)
    for net_name, nl in net_group_dict.items():
        divided_nl = defaultdict(list)
        for n in nl:
            assign = False
            for i, bzone in enumerate(problem_settings.blockage_x_intervals):
                if n.x_interval.end < bzone.begin:
                    divided_nl[i].append(n)
                    assign = True
                    break

            if not assign:
                divided_nl[len(problem_settings.blockage_x_intervals)].append(n)

        assert len(divided_nl) == 1, "Different target area in the same group..."

        col_no = list(divided_nl.keys())[0]
        n_nets_in_areas[col_no] += len(nl)
        # 保存
        col2ent_group_dict[col_no][net_name] = nl
    return col2ent_group_dict


def read_blockages(problem_settings: dict, col: int) -> dict:
    # allocate blockages
    reserved_areas = problem_settings.read_reserved_areas()

    blockages = defaultdict(lambda: defaultdict(list))
    for i in range(problem_settings.n_subchannels):
        height = (
            problem_settings.y_bottom_blockage
            + i * problem_settings.subchannel_interval
        )
        subgap_y_interval = Interval(height, height + problem_settings.subchannel_width)
        for ra in reserved_areas:
            overlapped_x_interval_size = problem_settings.subchannel_x_intervals[
                col
            ].overlap_size(ra.x_interval)
            overlapped_y_interval_size = subgap_y_interval.overlap_size(ra.y_interval)

            if overlapped_x_interval_size > 0 and overlapped_y_interval_size > 0:
                block_x_interval = Interval(
                    max(
                        problem_settings.subchannel_x_intervals[col].begin,
                        ra.x_interval.begin,
                    ),
                    min(
                        problem_settings.subchannel_x_intervals[col].end,
                        ra.x_interval.end,
                    ),
                )
                block_y_interval = Interval(
                    max(subgap_y_interval.begin, ra.y_interval.begin)
                    - subgap_y_interval.begin,
                    min(subgap_y_interval.end, ra.y_interval.end)
                    - subgap_y_interval.begin,
                )
                b = entities.Blockage(
                    block_x_interval.begin,
                    block_x_interval.end,
                    block_y_interval.begin,
                    block_y_interval.end,
                )
                blockages[col][i].append(b)

    return blockages


def get_unallocatable_net_dict_after_divisoin(
    net_group_dict: dict, target_area_width: Decimal, shield_width: Decimal
) -> dict[str, list[entities.Net]]:
    """対象配線領域に対し, ネットを分割しても配線できないネットを返す

    Args:
        net_group_dict (dict): _description_
        target_area_width (Decimal): _description_
        shield_width (Decimal): _description_

    Returns:
        dict[str, list[entities.Net]]: _description_
    """
    unallocatable_net_dict = {}
    for net_name, nl in net_group_dict.items():
        for net in nl:
            if net.shield_type.is_none():
                allocatable_width_max = target_area_width - (
                    net.upper_space + net.lower_space
                )
            else:
                allocatable_width_max = target_area_width - (
                    net.upper_space * 2 + net.lower_space * 2 + shield_width * 2
                )

            if allocatable_width_max <= 0:
                unallocatable_net_dict[net_name] = nl
                break
    return unallocatable_net_dict


def run(net_group_dict: dict, problem_settings: dict) -> dict:
    """net_group_dict: local配線すべきnetのみの情報"""

    # 配線できなかったネットを格納する
    unallocatable_net_group_dict = defaultdict(list)

    # NOTE:sub-channelにそもそも分割しても配線できなものは,予め省いておく
    remove_net_dict = get_unallocatable_net_dict_after_divisoin(
        net_group_dict,
        problem_settings.subchannel_width,
        problem_settings.shield_width,
    )
    for net_name, nl in remove_net_dict.items():
        assert (
            not net_name in unallocatable_net_group_dict
        ), "Net Name Duplication Error"
        unallocatable_net_group_dict[net_name] = nl
        # 入力から削除
        if net_name in net_group_dict:
            del net_group_dict[net_name]

    # col毎にnetlistを分ける -> divided_nl_dict_dict[col][name] = nl
    net_group_dict_by_block = divide_nets_by_block(net_group_dict, problem_settings)

    # subchannelを生成
    subchannel_dict = {}
    for col in range(problem_settings.num_subchannel_cols):
        # suchannel初期化
        subchannels = problem_settings.generate_subchannels()
        # allocate blockages
        blockages = read_blockages(problem_settings, col)
        for i, subchannel in enumerate(subchannels):
            for b in blockages[col][i]:
                subchannel.allocate(b)
        subchannel_dict[col] = subchannels

    ##################################
    # Routing by block
    ##################################
    for col in range(problem_settings.num_subchannel_cols):
        subchannels: list = subchannel_dict[col]
        net_group_dict: dict[str, list] = net_group_dict_by_block[col]

        # 束配線と配線へ分ける
        subchannel = problem_settings.generate_subchannel()
        oids, bundles = preprocessing.run(net_group_dict, problem_settings, subchannel)

        print("=" * 50)
        print(f"Subchannel Block: {col}")
        print(f"#Oids: {len(oids)}")
        print(f"#Bundles: {len(bundles)}")

        ##################################
        # 束配線
        ##################################
        preallocated_subchannels, unallocatable_net_group_names = (
            algorithms.greedy_allocate_bundles(bundles, subchannels)
        )
        n_subchannels_used_for_bundles = utils.get_n_routing_areas_used(
            preallocated_subchannels
        )

        # 配線できなかった束ネットを格納する.
        if unallocatable_net_group_names != []:
            for net_name in unallocatable_net_group_names:
                unallocatable_net_group_dict[net_name] = net_group_dict[net_name]

        ##################################
        # 配線
        ##################################
        used_subchannels, remaining_subchannels, remaining_oids = (
            algorithms.overlaped_interval_dict_routing(
                oids, preallocated_subchannels, problem_settings
            )
        )
        if remaining_oids != []:
            for oid in remaining_oids:
                print(f"Unallocatable oids: {oid.name}")
                unallocatable_net_group_dict[oid.name] = net_group_dict[oid.name]

        total_subchannels = used_subchannels + remaining_subchannels
        subchannel_dict[col] = total_subchannels
        n_subchannels_used_for_total = utils.get_n_routing_areas_used(total_subchannels)

        print("Routing Summary")
        print(f"#subchannels used for bundles: {n_subchannels_used_for_bundles}")
        print(f"#subchannels used for total: {n_subchannels_used_for_total}")

    return subchannel_dict, unallocatable_net_group_dict
