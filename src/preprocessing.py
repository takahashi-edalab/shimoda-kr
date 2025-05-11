from decimal import Decimal
from gcr import containers, entities


def divide_width(w: Decimal, factor: Decimal) -> list[Decimal]:
    """複数のnetに分割するときに, 各netの幅を決定する
    w=8, factor=3
    [3, 3, 2]
    w=8, factor=2
    [2, 2, 2, 2]

    Args:
        w (Decimal): トランクの幅
        factor (Decimal): 分割数

    Returns:
        list[Decimal]: 分割後の幅のリスト
    """
    quotient = int(w // factor)
    remainder = w % factor
    if remainder == Decimal("0.0"):
        remainders = []
    else:
        remainders = [remainder]
    return [factor] * quotient + remainders


def trunk_division(
    net: entities.Net, shield_width: Decimal, routing_area_width: Decimal
) -> list[entities.Net]:
    """対象配線領域の幅に応じてトランクを分割する

    Args:
        net (entities.Net): 分割するネット
        shield_width (Decimal): シールド線の幅
        routing_area_width (Decimal): 対象配線領域の幅

    Raises:
        ValueError: 配線できるように分割できない場合

    Returns:
        list[entities.Net]: 分割後のネットリスト
    """
    if net.shield_type.is_none():
        allocatable_width_max = routing_area_width - (net.upper_space + net.lower_space)
    else:
        allocatable_width_max = routing_area_width - (
            net.upper_space * 2 + net.lower_space * 2 + shield_width * 2
        )

    if allocatable_width_max <= 0:
        raise ValueError(f"allocatable_width_max <= 0: {allocatable_width_max}")

    # 分割後の幅を決定する
    divided_widths = divide_width(net.width, allocatable_width_max)
    # 分割後のネットリストを生成する
    new_nl = []
    for i, width in enumerate(divided_widths):
        new_net = entities.Net(
            name=f"{net.name}_c{i}",
            layer=net.layer,
            width=width,
            space=net.upper_space,
            pins=net.pins,
            shield_type=net.shield_type,
            group_no=net.group_no,
        )
        new_nl.append(new_net)
    return new_nl


def grouping(
    netlist: list, problem_settings: dict, routing_area
) -> list[list[entities.Net]]:
    """ネットリストをグループ化する

    Args:
        netlist (list): ネットリスト
        problem_settings (dict): 問題設定クラス
        routing_area (_type_): 対象配線領域のクラス

    Returns:
        list[list[entities.Net]]: グループのリスト
    """
    groups = []
    tmp_nl = []
    for n in netlist:
        tmp_nl.append(n)
        ig = problem_settings.generate_overlapped_interval_dict(tmp_nl)
        if not routing_area.allocatable(ig):
            if len(tmp_nl) == 1:
                # NOTE: 束netの要素の一つだが, 単体で対象配線領域に配線不可能 -> 分割
                new_nl = trunk_division(
                    tmp_nl[0], problem_settings.shield_width, routing_area.width
                )
                groups += [[n] for n in new_nl]
            else:
                groups.append(tmp_nl[:-1])
                tmp_nl = tmp_nl[-1:]

    if tmp_nl != []:
        groups.append(tmp_nl)
    return groups


def run(
    net_group_dict: dict, problem_settings: dict, routing_area
) -> tuple[list[containers.OverlappedIntervalDict], list[containers.Bundle]]:
    """前処理によって, ネットリストを束配線と事後配線に分ける

    Args:
        net_group_dict (dict): ネット
        problem_settings (dict): _description_
        routing_area (_type_): _description_

    Returns:
        tuple[list[containers.OverlappedIntervalDict], list[containers.Bundle]]: _description_
    """
    oids = []
    bundles = []

    for net_group_name, nl in net_group_dict.items():
        oid = problem_settings.generate_overlapped_interval_dict(nl)

        # 1gapで配線できる場合: 事後配線に追加
        if routing_area.allocatable(oid):
            oids.append(oid)
            continue

        # その他: 事前配線に追加
        if len(nl) == 1:
            # 1netでそもそも配線できない場合, 分割する
            new_nl = trunk_division(
                nl[0], problem_settings.shield_width, routing_area.width
            )
            groups = grouping(new_nl, problem_settings, routing_area)
        else:
            groups = grouping(nl, problem_settings, routing_area)

        # 各グループをoidにまとめ, Bundleにする
        components_of_one_net = []
        for sub_nl in groups:
            ig = problem_settings.generate_overlapped_interval_dict(sub_nl)
            components_of_one_net.append(ig)
        b = containers.Bundle(net_group_name, components_of_one_net)
        bundles.append(b)
    return oids, bundles
