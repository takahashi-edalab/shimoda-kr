import heapq
import numpy as np
from decimal import Decimal
from gcr import entities, routing_area
from collections import defaultdict
from intervaltree import Interval
from functools import cmp_to_key


def greedy_allocate_bundles(
    bundles: list, ras: list[routing_area.RoutingArea]
) -> tuple[list, dict[str, list[entities.Net]]]:
    """スライディングウィンドウで最適な連続する配線領域を選択していく

    Args:
        bundles (list): 束ネットリスト
        ras (list): 対戦領域リスト

    Returns:
        tuple[list, dict[str, list[entities.Net]]]: _description_
    """
    sorted_bundles = sorted(bundles, key=lambda x: len(x.pins), reverse=True)
    gap_heights = [g.height for g in ras]

    unallocatable_net_group_names = []

    for b in sorted_bundles:
        best_vwl = Decimal(float("inf"))
        best_start_idx = 0

        for i in range(len(gap_heights) - len(b) + 1):
            # assignable check
            assignable = True
            for g, elm in zip(ras[i : i + len(b)], b):
                if not g.allocatable(elm):
                    assignable = False
                    break

            if not assignable:
                continue

            heights = gap_heights[i : i + len(b)]
            vwl = b.vertical_wirelength_with_multi_y(heights)
            if best_vwl > vwl:
                best_vwl = vwl
                best_start_idx = i

        if best_vwl == Decimal(float("inf")):
            print(f"Cannot assign: {b.name}")
            unallocatable_net_group_names.append(b.name)
        else:
            # assign
            for g, elm in zip(ras[best_start_idx : best_start_idx + len(b)], b):
                offset = g.get_offset(elm)
                y_max_with_space = g.allocate(elm)
                g.init_ceilings.append(offset)
                g.init_ceilings.append(y_max_with_space)
    return ras, unallocatable_net_group_names


def get_optimal_routing_areas(oid, ras: list) -> list[routing_area.RoutingArea]:
    """最適な配線領域を取得する関数

    Args:
        oid (_type_): _description_
        ras (list): _description_

    Returns:
        list: _description_
    """
    optimal_ras = [
        ra for ra in ras if oid.y_mid_lower <= ra.y_mid and ra.y_mid <= oid.y_mid_upper
    ]
    return optimal_ras


def get_best_routing_area(
    oid, ras: list[routing_area.RoutingArea]
) -> routing_area.RoutingArea:
    ra_heights = np.array([ra.y_mid for ra in ras])
    diff = np.abs(ra_heights.T - np.array([oid.y_mid])).T
    sorted_args_diff = np.argsort(diff)
    first_close_idx = sorted_args_diff[0]
    # 残りのgapが一つしかない場合には2ndは1stと同一にする
    if len(ra_heights) == 1:
        second_close_idx = first_close_idx
    else:
        second_close_idx = sorted_args_diff[1]

    # extract ras
    first_close_ra = ras[first_close_idx]
    second_close_ra = ras[second_close_idx]
    # calc wirelength
    first_wl = oid.vertical_wirelength(first_close_ra.y_mid)
    second_wl = oid.vertical_wirelength(second_close_ra.y_mid)
    if first_wl < second_wl:
        return first_close_ra
    else:
        return second_close_ra


def left_edge(oids: list, ras: list[routing_area.RoutingArea], use_gco=False):
    """Left-Edgeのように, 左から順に配線していく手法

    Args:
        oids (list): _description_
        ras (list[routing_area.RoutingArea]): _description_
        use_gco (bool, optional): _description_. Defaults to False.

    Returns:
        _type_: _description_
    """
    # Left-edgeの基準線
    remaining_oids = sorted(oids, key=lambda x: x.x_interval.begin)
    # 配線した配線領域
    routed_ras = []
    # 天井制約を保持する優先度付きキュー
    height_limit_queue = []
    heapq.heapify(height_limit_queue)
    # 残りの配線領域とネット
    remaining_ras = ras
    # 配線開始
    while remaining_oids:
        if len(remaining_ras) == 0:
            break

        # target raを選択
        if use_gco:
            remaining_ras = prioritize_routing_areas(
                remaining_ras,
                remaining_oids=remaining_oids,
                use_random=False,
                congestion_first=True,
            )
        target_ra = remaining_ras.pop(0)
        routed_ras.append(target_ra)

        # target gapに既にある障害物からceilingを登録
        for c in target_ra.init_ceilings:
            heapq.heappush(height_limit_queue, c)

        while True:
            # 天井制約線を取得
            if len(height_limit_queue) == 0:
                height_limit = None  # gap width
            else:
                height_limit = height_limit_queue[0]

            x = Decimal(float("-inf"))
            remove_oids = []
            for oid in remaining_oids:
                if all(
                    [
                        x < oid.x_interval.begin,
                        target_ra.allocatable(oid, height_limit),
                    ]
                ):
                    target_ra.allocate(oid, height_limit)
                    x = oid.x_interval.end
                    remove_oids.append(oid)

            # 配線できるものがなければ次のRAへ
            if remove_oids == []:
                if height_limit is None:
                    # RAの上辺の高さの天井制約線で配線できなかった場合, 次のRAへ
                    break
                else:
                    # 現状の天井制約を破棄し, 次にゆるい天井制約で配線を試みる
                    heapq.heappop(height_limit_queue)
                    continue

            # 配線したnetを削除
            for oid in remove_oids:
                remaining_oids.remove(oid)

    return routed_ras, remaining_ras, remaining_oids


def cap_sort(oids: list) -> list:
    """CAPにおけるネットの優先順位付けを行う関数

    Args:
        oids (list): _description_

    Returns:
        list: _description_
    """

    def __cap(oid1, oid2) -> int:
        """
        Returns:
        int: -1 if oid1 < oid2; 1 otherwise
        """
        # 幅広優先
        if oid1.width > oid2.width:
            return -1
        elif oid1.width < oid2.width:
            return 1

        # 幅が一緒の場合, 左優先
        if oid1.x_interval.begin < oid2.x_interval.begin:
            return -1
        else:
            return 1

    return sorted(oids, key=cmp_to_key(__cap))


def max_density_zones(oids: list) -> tuple[float, list[Interval]]:
    """最大混雑度とその区間を取得する関数

    Args:
        oids (list): _description_

    Returns:
        tuple[float, list[Interval]]: _description_
    """
    diff_density = defaultdict(list)
    for oid in oids:
        diff_density[oid.x_interval.begin].append((oid, "add"))
        diff_density[oid.x_interval.end].append((oid, "remove"))

    max_density = 0
    start_x = None
    zones = []
    conflict_nets = []
    # sort via key
    for k, nl in sorted(diff_density.items(), key=lambda k: k[0]):
        # print(k)
        for t in nl:
            net, command = t
            if command == "add":
                conflict_nets.append(net)
            else:
                conflict_nets.remove(net)

        if conflict_nets == []:
            continue

        density = sum([n.width for n in conflict_nets])
        if command == "add":
            if max_density < density:
                max_density = density
                start_x = k
                zones = []
            elif max_density == density:
                start_x = k
        else:
            if not start_x is None:
                z = Interval(start_x, k)
                zones.append(z)
                start_x = None

    return max_density, zones


def is_desired_net(
    available_start_x: Decimal, density_zones: Interval, oid: entities.Allocatables
) -> bool:
    """最大混雑度がleft edgeの基準点, 配線しようとしているnet.minx]の区間にあるかどうかを返す関数

    Args:
        available_start_x (Decimal): _description_
        density_zones (Interval): _description_
        oid (entities.Allocatables): _description_

    Returns:
        bool: _description_
    """
    for z in density_zones:
        if available_start_x < z.begin and z.begin < oid.x_interval.begin:
            return False
    return True


def cap(oids: list, ras: list[routing_area.RoutingArea], use_gco=False):
    # 配線した配線領域
    routed_ras = []
    # 天井制約を保持する優先度付きキュー
    height_limit_queue = []
    heapq.heapify(height_limit_queue)
    # 残りの配線領域とネット
    remaining_oids = oids
    remaining_ras = ras
    # capの優先順位に従ってソート
    remaining_oids = cap_sort(oids)
    # start cap
    while remaining_oids:
        # 配線しきれない場合には返す
        if len(remaining_ras) == 0:
            break

        # target raを選択
        if use_gco:
            remaining_ras = prioritize_routing_areas(
                remaining_ras,
                remaining_oids=remaining_oids,
                use_random=False,
                congestion_first=True,
            )
        target_ra = remaining_ras.pop(0)
        routed_ras.append(target_ra)

        # target gapに既にある障害物からceilingを登録
        for c in target_ra.init_ceilings:
            heapq.heappush(height_limit_queue, c)

        while True:
            # 天井制約線を取得
            if len(height_limit_queue) == 0:
                height_limit = None  # gap width
            else:
                height_limit = height_limit_queue[0]

            oid_is_routed = False
            # left-edgeの基準線
            x = Decimal(float("-inf"))
            # 最大混雑度の区間を取得
            _, zones = max_density_zones(remaining_oids)
            # 天井制約候補リスト
            new_ceiling_heights = []
            while True:
                is_updated = False
                for oid in remaining_oids:
                    if all(
                        [
                            x < oid.x_interval.begin,
                            is_desired_net(x, zones, oid),
                            target_ra.allocatable(oid, height_limit),
                        ]
                    ):
                        # 配線したら天井を登録
                        height = target_ra.allocate(oid, height_limit)
                        new_ceiling_heights.append(height)
                        # left-edgeの基準線を更新
                        x = oid.x_interval.end
                        # 配線したnetを削除
                        remaining_oids.remove(oid)
                        is_updated = True
                        oid_is_routed = True
                        break

                if not is_updated:
                    break

            # 何も配線できなかった場合
            if not oid_is_routed:
                if height_limit is None:
                    # RAの上辺の高さの天井制約線で配線できなかった場合, 次のRAへ
                    break
                else:
                    # 現状の天井制約を破棄し, 次にゆるい天井制約で配線を試みる
                    heapq.heappop(height_limit_queue)
                    continue

            # 天井制約候補へ追加
            for h in new_ceiling_heights:
                heapq.heappush(height_limit_queue, h)

    return routed_ras, remaining_ras, remaining_oids


def wirelength_priority(
    oids: list, gap_heights: list[Decimal], target_gap_height: Decimal
):
    n_nets = len(oids)

    if len(gap_heights) == 0:
        return np.zeros((n_nets))

    net_heights = np.array([ig.y_mid for ig in oids])
    gap_heights = np.array(gap_heights)
    repeat_gap_heights = np.tile(gap_heights, (n_nets, 1))
    diff = np.abs(repeat_gap_heights.T - np.array(net_heights)).T
    sorted_args_diff = np.argsort(diff)
    # 1st, 2ndの距離のgapの高さのindexを取得
    first_close = sorted_args_diff[:, 0]
    if len(gap_heights) == 1:
        # 残りのgapが一つしかない場合には2ndは1stと同一にする
        second_close = first_close
    else:
        second_close = sorted_args_diff[:, 1]

    priorities = []
    for ig, g1y, g2y in zip(oids, gap_heights[first_close], gap_heights[second_close]):
        closest_gap_wirelength = min(
            ig.vertical_wirelength(g1y), ig.vertical_wirelength(g2y)
        )
        # print(closest_gap_wirelength)
        target_gap_wirelength = ig.vertical_wirelength(target_gap_height)
        # print(target_gap_wirelength)
        p = closest_gap_wirelength - target_gap_wirelength
        priorities.append(p)
    return priorities


def criticality_based_priority(
    oids: list,
    remaining_ras: list[routing_area.RoutingArea],
    target_ra: routing_area.RoutingArea,
) -> list:
    """CCAPにおけるネットの優先順位付けを行う関数

    Args:
        oids (list): _description_

    Returns:
        list: _description_
    """

    def __critical_wirelength(oid1, oid2) -> int:
        """
        Returns:
        int: -1 if oid1 < oid2; 1 otherwise
        """
        # 幅広優先
        if oid1.width > oid2.width:
            return -1
        elif oid1.width < oid2.width:
            return 1

        # dist-priority: 大きいほうが優先
        if oid1.dist_priority > oid2.dist_priority:
            return -1
        elif oid1.dist_priority < oid2.dist_priority:
            return 1

        # dist-priorityが一緒の場合, 左優先
        if oid1.x_interval.begin < oid2.x_interval.begin:
            return -1
        else:
            return 1

    gap_heights = [g.y_mid for g in remaining_ras]
    dpriority = wirelength_priority(oids, gap_heights, target_ra.y_mid)
    for oid, p in zip(oids, dpriority):
        oid.dist_priority = p

    return sorted(oids, key=cmp_to_key(__critical_wirelength))


def prioritize_routing_areas(
    ras: list[routing_area.RoutingArea],
    remaining_oids=None,
    use_random=False,
    congestion_first=True,
) -> list[routing_area.RoutingArea]:
    if use_random:
        import random

        random.seed(0)
        random.shuffle(ras)

    else:
        assert remaining_oids is not None, "congestion-based gap selectoin uses oids..."

        # congestion初期化
        for ra in ras:
            ra.congestion = 0

        # opt intervalとの重なり調査
        for oid in remaining_oids:
            opt_ras = get_optimal_routing_areas(oid, ras)
            if opt_ras == []:
                best_ra = get_best_routing_area(oid, ras)
                opt_ras = [best_ra]

            n_ras = len(opt_ras)
            for ra in opt_ras:
                ra.congestion += 1 / n_ras

        ras = sorted(ras, reverse=congestion_first, key=lambda x: x.congestion)

    return ras


def ccap(
    oids: list,
    ras: list[routing_area.RoutingArea],
    use_random=False,
    congestion_first=True,
):
    # 配線した配線領域
    routed_ras = []
    # 天井制約を保持する優先度付きキュー
    height_limit_queue = []
    heapq.heapify(height_limit_queue)
    # 残りの配線領域とネット
    remaining_oids = oids
    remaining_ras = ras
    # 配線開始
    while remaining_oids:
        # 配線しきれなかった場合
        if len(remaining_ras) == 0:
            break

        # raに優先順位をつけ, 一番上のものを取得
        remaining_ras = prioritize_routing_areas(
            remaining_ras,
            remaining_oids=remaining_oids,
            use_random=use_random,
            congestion_first=congestion_first,
        )
        target_ra = remaining_ras.pop(0)
        routed_ras.append(target_ra)

        # target gapに既にある障害物からceilingを登録
        for c in target_ra.init_ceilings:
            heapq.heappush(height_limit_queue, c)

        # 各トランクの優先順位付け
        remaining_oids = criticality_based_priority(
            remaining_oids, remaining_ras, target_ra
        )

        while True:
            # 天井制約線を取得
            if len(height_limit_queue) == 0:
                height_limit = None  # gap width
            else:
                height_limit = height_limit_queue[0]

            oid_is_routed = False
            # left-edgeの基準線
            x = Decimal(float("-inf"))
            # 最大混雑度の区間を取得
            _, zones = max_density_zones(remaining_oids)
            # 天井制約候補リスト
            new_ceiling_heights = []
            while True:
                is_updated = False
                for oid in remaining_oids:
                    if all(
                        [
                            x < oid.x_interval.begin,
                            is_desired_net(x, zones, oid),
                            target_ra.allocatable(oid, height_limit),
                        ]
                    ):
                        # 配線したら天井を登録
                        height = target_ra.allocate(oid, height_limit)
                        new_ceiling_heights.append(height)
                        # left-edgeの基準線を更新
                        x = oid.x_interval.end
                        # 配線したnetを削除
                        remaining_oids.remove(oid)
                        is_updated = True
                        oid_is_routed = True
                        break

                if not is_updated:
                    break

            # 何も配線できなかった場合
            if not oid_is_routed:
                if height_limit is None:
                    # RAの上辺の高さの天井制約線で配線できなかった場合, 次のRAへ
                    break
                else:
                    # 現状の天井制約を破棄し, 次にゆるい天井制約で配線を試みる
                    heapq.heappop(height_limit_queue)
                    continue

            # 天井制約候補へ追加
            for h in new_ceiling_heights:
                heapq.heappush(height_limit_queue, h)

    return routed_ras, remaining_ras, remaining_oids


def overlaped_interval_dict_routing(oids, ras, problem_settings):
    """配線する関数

    Args:
        oids (_type_): _description_
        ras (_type_): _description_
        problem_settings (_type_): _description_

    Raises:
        ValueError: _description_

    Returns:
        _type_: _description_
    """
    if problem_settings.algorithm_name == "ccap":
        used_ras, remaining_ras, remaining_oids = ccap(oids, ras)
    elif problem_settings.algorithm_name == "cap":
        used_ras, remaining_ras, remaining_oids = cap(
            oids, ras, use_gco=problem_settings.use_gco
        )
    elif problem_settings.algorithm_name == "le":
        used_ras, remaining_ras, remaining_oids = left_edge(
            oids, ras, use_gco=problem_settings.use_gco
        )
    else:
        raise ValueError("Invalid algorithm")

    return used_ras, remaining_ras, remaining_oids
