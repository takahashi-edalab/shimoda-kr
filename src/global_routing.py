from gcr import utils
from src import algorithms, preprocessing


def run(net_group_dict: dict, problem_settings: dict) -> None:
    """net_group_dict: global配線すべきnetのみの情報"""

    # grouping ...
    gap = problem_settings.generate_gap()
    oids, bundles = preprocessing.run(net_group_dict, problem_settings, gap)
    print("=" * 50)
    print("Global Routing")
    print(f"#Oids: {len(oids)}")
    print(f"#Bundles: {len(bundles)}")

    # init_gaps
    gaps = problem_settings.generate_gaps()

    ##################################
    # 束配線
    ##################################
    preallocated_gaps, unallocatable_net_group_names = (
        algorithms.greedy_allocate_bundles(bundles, gaps)
    )
    n_gaps_used_for_bundles = utils.get_n_routing_areas_used(preallocated_gaps)

    # 配線できなかった束ネットがある場合, 配線しきれないので終了
    if unallocatable_net_group_names != []:
        raise RuntimeError(f"Cannot allocate bundles: {unallocatable_net_group_names}")

    ##################################
    # 配線
    ##################################
    used_gaps, remaining_gaps, remaining_oids = (
        algorithms.overlaped_interval_dict_routing(
            oids, preallocated_gaps, problem_settings
        )
    )
    if remaining_oids != []:
        raise RuntimeError(f"Cannot assign oids: {remaining_oids}")

    total_gaps = used_gaps + remaining_gaps
    n_gaps_used_for_total = utils.get_n_routing_areas_used(total_gaps)

    print("Routing Summary")
    print(f"#gaps used for bundles: {n_gaps_used_for_bundles}")
    print(f"#gaps used for total: {n_gaps_used_for_total}")

    return total_gaps
