def _group_geometry_side(obj, vg):
    if not vg:
        return "center"
    idx = vg.index
    total_weight = 0.0
    weighted_x = 0.0
    mw = obj.matrix_world
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == idx and g.weight > 0.0005:
                total_weight += g.weight
                weighted_x += (mw @ v.co).x * g.weight
                break
    if total_weight <= 0.0005:
        return "center"
    avg_x = weighted_x / total_weight
    if avg_x > 0.02:
        return "left"
    if avg_x < -0.02:
        return "right"
    return "center"


def _target_side(name):
    if not name:
        return "center"
    if name.endswith(".L") or name.endswith("_l") or name.startswith("左"):
        return "left"
    if name.endswith(".R") or name.endswith("_r") or name.startswith("右"):
        return "right"
    return "center"


def _swap_lr_target(name):
    if not name:
        return name
    if name.endswith(".L"):
        return name[:-2] + ".R"
    if name.endswith(".R"):
        return name[:-2] + ".L"
    if name.startswith("左"):
        return "右" + name[1:]
    if name.startswith("右"):
        return "左" + name[1:]
    return name


def _resolve_side_aware_target(obj, src_vg, dst_name):
    """Correct obviously flipped L/R helper redirects using geometry side."""
    if not src_vg or not dst_name:
        return dst_name
    dst_side = _target_side(dst_name)
    if dst_side not in {"left", "right"}:
        return dst_name
    src_side = _group_geometry_side(obj, src_vg)
    if src_side in {"left", "right"} and src_side != dst_side:
        return _swap_lr_target(dst_name)
    return dst_name


def transfer_helper_weights(mesh_objects, redirect_map):
    """Merge helper-bone weights into target groups, then clear source weights.

    redirect_map shape:
      {source_vertex_group_name: target_vertex_group_name}
      or
      {source_vertex_group_name: {"target": target_vertex_group_name, "scale": 0.35}}

    Returns: (moved_vertex_count, detail_strings)
    """
    total_verts = 0
    details = []
    for obj in mesh_objects:
        for src_name, redirect in redirect_map.items():
            if isinstance(redirect, dict):
                dst_name = redirect.get("target")
                scale = float(redirect.get("scale", 1.0))
            else:
                dst_name = redirect
                scale = 1.0

            if not dst_name:
                continue

            src_vg = obj.vertex_groups.get(src_name)
            if not src_vg:
                continue
            resolved_dst_name = _resolve_side_aware_target(obj, src_vg, dst_name)
            auto_side_fixed = resolved_dst_name != dst_name
            dst_vg = obj.vertex_groups.get(resolved_dst_name)
            if not dst_vg:
                dst_vg = obj.vertex_groups.new(name=resolved_dst_name)
            src_idx = src_vg.index
            dst_idx = dst_vg.index
            moved = 0
            for v in obj.data.vertices:
                src_weight = dst_weight = 0.0
                for g in v.groups:
                    if g.group == src_idx:
                        src_weight = g.weight
                    if g.group == dst_idx:
                        dst_weight = g.weight
                if src_weight < 0.001:
                    continue

                # 保守合并：只填充目标组尚未占满的空间，避免一步把髋部/躯干过渡顶满。
                transferable = src_weight * scale
                merged_weight = min(1.0, dst_weight + transferable * max(0.0, 1.0 - dst_weight))
                dst_vg.add([v.index], merged_weight, 'REPLACE')
                src_vg.add([v.index], 0.0, 'REPLACE')
                moved += 1
            if moved:
                detail_target = resolved_dst_name
                detail_prefix = f"{src_name}→{detail_target}"
                if auto_side_fixed:
                    detail_prefix += " [auto-side]"
                if scale != 1.0:
                    details.append(f"{detail_prefix}x{scale:.2f}({moved}顶点)")
                else:
                    details.append(f"{detail_prefix}({moved}顶点)")
                total_verts += moved
    return total_verts, details


def cleanup_inner_thigh_d_weights(armature, mesh_objects):
    """Reduce D-bone contamination in the upper inner-thigh / groin centerline.

    XPS helper redirects can leave both 足D.L/R influencing the same inner-thigh
    region. The PMX reference keeps this area mostly on 下半身, so we:
    1. clear bilateral D influence near the centerline when 下半身 is dominant
    2. clear the opposite-side D influence in the upper groin band
    3. gently damp the same-side D when 下半身 already dominates that vertex
    """
    lower_body_name = "下半身"
    left_d_name = "足D.L"
    right_d_name = "足D.R"
    left_fk_name = "左足"
    right_fk_name = "右足"

    left_fk = armature.data.bones.get(left_fk_name)
    right_fk = armature.data.bones.get(right_fk_name)
    if not left_fk or not right_fk:
        return 0

    arm_mw = armature.matrix_world
    left_head = arm_mw @ left_fk.head_local
    left_tail = arm_mw @ left_fk.tail_local
    right_head = arm_mw @ right_fk.head_local
    right_tail = arm_mw @ right_fk.tail_local

    thigh_top = max(left_head.z, left_tail.z, right_head.z, right_tail.z)
    thigh_bottom = min(left_head.z, left_tail.z, right_head.z, right_tail.z)
    thigh_len = max(0.001, thigh_top - thigh_bottom)
    # 只处理最靠近腿根顶部的一小条，避免把整段大腿上部都洗成下半身。
    groin_bottom = thigh_top - thigh_len * 0.16

    hip_span = abs(right_head.x - left_head.x)
    if hip_span < 0.001:
        hip_span = max(abs(left_head.x), abs(right_head.x)) * 2.0
    center_band = max(0.02, hip_span * 0.10)
    center_hard_band = center_band * 0.65

    modified = 0
    for obj in mesh_objects:
        vg_lower = obj.vertex_groups.get(lower_body_name)
        vg_left = obj.vertex_groups.get(left_d_name)
        vg_right = obj.vertex_groups.get(right_d_name)
        if not vg_lower or not vg_left or not vg_right:
            continue

        idx_lower = vg_lower.index
        idx_left = vg_left.index
        idx_right = vg_right.index
        mw = obj.matrix_world

        for v in obj.data.vertices:
            v_world = mw @ v.co
            if v_world.z < groin_bottom or v_world.z > thigh_top + 0.001:
                continue

            lower_w = left_w = right_w = 0.0
            for g in v.groups:
                if g.group == idx_lower:
                    lower_w = g.weight
                elif g.group == idx_left:
                    left_w = g.weight
                elif g.group == idx_right:
                    right_w = g.weight

            d_total = left_w + right_w
            if d_total < 0.05:
                continue

            vx = v_world.x
            changed = False

            if vx > 0.0 and right_w > 0.001:
                vg_right.add([v.index], 0.0, 'REPLACE')
                lower_w = min(1.0, lower_w + right_w)
                vg_lower.add([v.index], lower_w, 'REPLACE')
                d_total -= right_w
                right_w = 0.0
                changed = True
            elif vx < 0.0 and left_w > 0.001:
                vg_left.add([v.index], 0.0, 'REPLACE')
                lower_w = min(1.0, lower_w + left_w)
                vg_lower.add([v.index], lower_w, 'REPLACE')
                d_total -= left_w
                left_w = 0.0
                changed = True

            if abs(vx) <= center_hard_band:
                # 中线附近只清对侧串腿的 D 骨，不再继续削同侧 D。
                # 这样能保住大腿根仍然由本侧 足D 参与驱动。
                modified += 1 if changed else 0
                continue

            if abs(vx) > center_band * 1.25:
                continue

            if changed:
                modified += 1

    return modified


def restore_upper_thigh_d_influence(armature, mesh_objects):
    """Restore same-side D influence in the upper thigh root band.

    After helper redirects and hip cleanup, the upper thigh can become almost
    fully controlled by 下半身. The reference PMX still keeps some same-side
    足D influence below the groin centerline, so we rebuild a narrow band where
    下半身 gradually gives way to the local 足D bone.
    """
    pairs = (
        ("左足", "足D.L", "足D.R"),
        ("右足", "足D.R", "足D.L"),
    )
    arm_mw = armature.matrix_world
    modified = 0

    for fk_name, d_name, opp_d_name in pairs:
        fk_bone = armature.data.bones.get(fk_name)
        if not fk_bone:
            continue

        hip = arm_mw @ fk_bone.head_local
        knee = arm_mw @ fk_bone.tail_local
        side_sign = -1.0 if hip.x < 0.0 else 1.0
        z_top = max(hip.z, knee.z)
        z_bottom = min(hip.z, knee.z)
        thigh_len = max(0.001, z_top - z_bottom)
        band_bottom = z_top - thigh_len * 0.32
        center_exclude = max(0.025, abs(hip.x) * 0.20)
        side_extent = max(center_exclude * 1.2, abs(hip.x) * 0.90)

        for obj in mesh_objects:
            vg_lower = obj.vertex_groups.get("下半身")
            vg_d = obj.vertex_groups.get(d_name)
            vg_opp = obj.vertex_groups.get(opp_d_name)
            if not vg_lower or not vg_d:
                continue

            idx_lower = vg_lower.index
            idx_d = vg_d.index
            idx_opp = vg_opp.index if vg_opp else -1
            mw = obj.matrix_world

            for v in obj.data.vertices:
                co = mw @ v.co
                if co.z < band_bottom or co.z > z_top + 0.001:
                    continue
                if side_sign < 0:
                    if co.x >= -center_exclude or abs(co.x) > side_extent:
                        continue
                else:
                    if co.x <= center_exclude or abs(co.x) > side_extent:
                        continue

                lower_w = d_w = opp_w = 0.0
                for g in v.groups:
                    if g.group == idx_lower:
                        lower_w = g.weight
                    elif g.group == idx_d:
                        d_w = g.weight
                    elif g.group == idx_opp:
                        opp_w = g.weight

                if lower_w < 0.20:
                    continue

                if opp_w > 0.001:
                    vg_opp.add([v.index], 0.0, 'REPLACE')
                    lower_w = min(1.0, lower_w + opp_w)
                    vg_lower.add([v.index], lower_w, 'REPLACE')
                    modified += 1

                t = (z_top - co.z) / max(0.001, z_top - band_bottom)
                target_d = 0.12 + 0.36 * t
                if d_w >= target_d - 0.01:
                    continue

                transfer = min(lower_w, target_d - d_w)
                if transfer < 0.001:
                    continue

                vg_lower.add([v.index], max(0.0, lower_w - transfer), 'REPLACE')
                vg_d.add([v.index], min(1.0, d_w + transfer), 'REPLACE')
                modified += 1

    return modified


def reinforce_mid_thigh_d_influence(armature, mesh_objects):
    """Increase same-side 足D influence in the upper/mid thigh control band.

    Some XPS rigs keep enough D weight near the groin but still feel "dead" in
    the upper thigh because the next band down is dominated by 下半身. This
    pass reinforces a wider, lower band so rotating 足D visibly moves the upper
    thigh without pushing influence into the knee/lower leg.
    """
    pairs = (
        ("左足", "足D.L", "足D.R"),
        ("右足", "足D.R", "足D.L"),
    )
    arm_mw = armature.matrix_world
    modified = 0

    for fk_name, d_name, opp_d_name in pairs:
        fk_bone = armature.data.bones.get(fk_name)
        if not fk_bone:
            continue

        hip = arm_mw @ fk_bone.head_local
        knee = arm_mw @ fk_bone.tail_local
        side_sign = -1.0 if hip.x < 0.0 else 1.0
        z_top = max(hip.z, knee.z)
        z_bottom = min(hip.z, knee.z)
        thigh_len = max(0.001, z_top - z_bottom)
        # 中段控制带再放宽一点：现在不是目标值太低，而是命中区域太窄。
        # 覆盖到腿根顶部附近（不再留出明显空带），避免“足D能带小腿但带不动大腿根”。
        band_top = z_top + thigh_len * 0.02
        band_bottom = z_top - thigh_len * 0.72
        center_exclude = max(0.012, abs(hip.x) * 0.07)
        side_extent = max(center_exclude * 2.4, abs(hip.x) * 1.35)

        for obj in mesh_objects:
            vg_lower = obj.vertex_groups.get("下半身")
            vg_d = obj.vertex_groups.get(d_name)
            vg_opp = obj.vertex_groups.get(opp_d_name)
            vg_fk = obj.vertex_groups.get(fk_name)
            vg_template = obj.vertex_groups.get(f"__CTMMD_SRC__{fk_name}")
            if not vg_lower or not vg_d:
                continue

            idx_lower = vg_lower.index
            idx_d = vg_d.index
            idx_opp = vg_opp.index if vg_opp else -1
            idx_fk = vg_fk.index if vg_fk else -1
            idx_template = vg_template.index if vg_template else -1
            mw = obj.matrix_world

            for v in obj.data.vertices:
                co = mw @ v.co
                if co.z < band_bottom or co.z > band_top:
                    continue
                top_ratio = (co.z - band_bottom) / max(0.001, (band_top - band_bottom))
                top_ratio = max(0.0, min(1.0, top_ratio))
                dynamic_center_exclude = max(0.006, center_exclude * (1.0 - 0.45 * top_ratio))
                if side_sign < 0:
                    if co.x >= -dynamic_center_exclude or abs(co.x) > side_extent:
                        continue
                else:
                    if co.x <= dynamic_center_exclude or abs(co.x) > side_extent:
                        continue

                lower_w = d_w = opp_w = template_w = fk_w = 0.0
                for g in v.groups:
                    if g.group == idx_lower:
                        lower_w = g.weight
                    elif g.group == idx_d:
                        d_w = g.weight
                    elif g.group == idx_opp:
                        opp_w = g.weight
                    elif g.group == idx_fk:
                        fk_w = g.weight
                    elif g.group == idx_template:
                        template_w = g.weight

                if opp_w > 0.001:
                    vg_opp.add([v.index], 0.0, 'REPLACE')
                    lower_w = min(1.0, lower_w + opp_w)
                    vg_lower.add([v.index], lower_w, 'REPLACE')
                    modified += 1

                # 这里不再只把模板当“目标值参考”，而是把它视为
                # “应恢复回足D的原始 XPS 大腿控制分布”。
                # 这样更接近“把右足/左足的大腿权重直接交还给足D”。
                template_target = template_w * 0.98 if template_w > 0.001 else 0.0
                # 中段最小目标再抬一档，优先保证大腿控制感。
                # 越靠近腿根顶部，足D最低占比越高。
                min_floor = 0.58 + 0.12 * top_ratio
                # 同侧原腿骨仍有权重时，强制把一部分主控转交给足D，减少“双控导致足D不明显”。
                fk_target = fk_w * (0.86 + 0.10 * top_ratio) if fk_w > 0.001 else 0.0
                target_d = max(min_floor, template_target, fk_target)
                if d_w >= target_d - 0.01:
                    continue
                # 只有在“下半身、模板、同侧FK”都没有可转移来源时才跳过；
                # 避免腿根区域因为 lower_w 偏低而错过把 FK 控制权转交给足D。
                if lower_w <= 0.02 and template_target <= 0.001 and fk_w <= 0.001:
                    continue

                needed = target_d - d_w
                if needed < 0.001:
                    continue

                # 优先直接把模板所代表的原始腿骨控制分布恢复到足D；
                # 下半身只负责让总量别过满，而不是唯一来源。
                new_d = min(1.0, d_w + needed)
                vg_d.add([v.index], new_d, 'REPLACE')

                if lower_w > 0.0:
                    lower_after = max(0.0, lower_w - min(lower_w, needed))
                    vg_lower.add([v.index], lower_after, 'REPLACE')
                # 主动下调同侧 FK（右足/左足）在同区域占比，避免 D/FK 双控互抢。
                if vg_fk and fk_w > 0.001:
                    fk_after = max(0.0, fk_w - min(fk_w, needed * 0.85))
                    vg_fk.add([v.index], fk_after, 'REPLACE')
                modified += 1

    return modified


def enforce_upper_leg_d_mastery(armature, mesh_objects):
    """Hard pass: force upper-leg root control to same-side 足D.

    This is a safety pass for rigs where Step 2 still leaves thigh-root control
    on FK leg bones. It only touches the upper leg band, preserving lower-leg.
    """
    pairs = (
        ("左足", "足D.L", "足D.R"),
        ("右足", "足D.R", "足D.L"),
    )
    arm_mw = armature.matrix_world
    modified = 0

    for fk_name, d_name, opp_d_name in pairs:
        fk_bone = armature.data.bones.get(fk_name)
        if not fk_bone:
            continue

        hip = arm_mw @ fk_bone.head_local
        knee = arm_mw @ fk_bone.tail_local
        side_sign = -1.0 if hip.x < 0.0 else 1.0
        z_top = max(hip.z, knee.z)
        z_bottom = min(hip.z, knee.z)
        thigh_len = max(0.001, z_top - z_bottom)
        band_top = z_top + thigh_len * 0.10
        band_bottom = z_top - thigh_len * 0.45
        center_exclude = 0.008
        side_extent = max(0.12, abs(hip.x) * 1.70)

        for obj in mesh_objects:
            vg_d = obj.vertex_groups.get(d_name)
            vg_fk = obj.vertex_groups.get(fk_name)
            vg_lower = obj.vertex_groups.get("下半身")
            vg_opp = obj.vertex_groups.get(opp_d_name)
            vg_template = obj.vertex_groups.get(f"__CTMMD_SRC__{fk_name}")
            vg_ub1 = obj.vertex_groups.get("上半身1")
            vg_ub2 = obj.vertex_groups.get("上半身2")
            if not vg_d or not vg_fk:
                continue

            idx_d = vg_d.index
            idx_fk = vg_fk.index
            idx_lower = vg_lower.index if vg_lower else -1
            idx_opp = vg_opp.index if vg_opp else -1
            idx_template = vg_template.index if vg_template else -1
            idx_ub1 = vg_ub1.index if vg_ub1 else -1
            idx_ub2 = vg_ub2.index if vg_ub2 else -1
            mw = obj.matrix_world

            for v in obj.data.vertices:
                co = mw @ v.co
                if co.z < band_bottom or co.z > band_top:
                    continue
                # 放宽到靠近中线的腿根区域，但仍阻止跨到对侧腿。
                if co.x * side_sign < -center_exclude or abs(co.x) > side_extent:
                    continue

                d_w = fk_w = lower_w = opp_w = template_w = ub1_w = ub2_w = 0.0
                for g in v.groups:
                    if g.group == idx_d:
                        d_w = g.weight
                    elif g.group == idx_fk:
                        fk_w = g.weight
                    elif g.group == idx_lower:
                        lower_w = g.weight
                    elif g.group == idx_opp:
                        opp_w = g.weight
                    elif g.group == idx_template:
                        template_w = g.weight
                    elif g.group == idx_ub1:
                        ub1_w = g.weight
                    elif g.group == idx_ub2:
                        ub2_w = g.weight

                # 上身过渡区不再“一刀切跳过”：
                # 腿根/臀下缘常带少量上半身权重，直接 continue 会导致该区域永远修不到。
                # 改为动态降权修复强度，既保留过渡，又允许足D拿回主控。
                ub_mix = min(1.0, ub1_w + ub2_w)

                if opp_w > 0.001 and vg_opp and vg_lower:
                    vg_opp.add([v.index], 0.0, 'REPLACE')
                    lower_w = min(1.0, lower_w + opp_w)
                    vg_lower.add([v.index], lower_w, 'REPLACE')
                    modified += 1

                top_ratio = (co.z - band_bottom) / max(0.001, (band_top - band_bottom))
                top_ratio = max(0.0, min(1.0, top_ratio))
                target_d = max(0.74 + 0.14 * top_ratio, fk_w * 0.90, template_w * 0.92)
                target_d *= (1.0 - 0.35 * ub_mix)
                if d_w >= target_d - 0.01:
                    continue

                need = target_d - d_w
                if need < 0.001:
                    continue

                take_fk = min(fk_w, need)
                fk_after = max(0.0, fk_w - take_fk)
                remain = need - take_fk
                take_lower = min(lower_w, remain) if remain > 0.0 else 0.0
                lower_after = max(0.0, lower_w - take_lower)
                new_d = min(1.0, d_w + take_fk + take_lower)

                # 腿根上段保持足D主控，但保留过渡，避免髋部硬切割。
                if top_ratio >= 0.50:
                    new_d = max(new_d, 0.80 if top_ratio < 0.75 else 0.86)
                    fk_after = 0.0
                    if vg_opp:
                        vg_opp.add([v.index], 0.0, 'REPLACE')
                    if vg_lower:
                        lower_after = max(lower_after, 1.0 - new_d)

                vg_d.add([v.index], min(1.0, new_d), 'REPLACE')
                vg_fk.add([v.index], max(0.0, fk_after), 'REPLACE')
                if vg_lower:
                    vg_lower.add([v.index], max(0.0, lower_after), 'REPLACE')
                modified += 1

    return modified


def absorb_helper_thigh_twist_to_d(mesh_objects):
    """Merge legacy helper thigh-twist groups into D-leg groups.

    Some XPS rigs keep upper-thigh root vertices mostly on helper groups
    like `unused bip001 xtra02/xtra04`, which makes 足D appear ineffective.
    Move these weights into 足D.L/R during Step 2.
    """
    mapping = (
        ("unused bip001 xtra02", "足D.R"),
        ("unused bip001 xtra04", "足D.L"),
    )
    modified = 0
    for obj in mesh_objects:
        for src_name, dst_name in mapping:
            src_vg = obj.vertex_groups.get(src_name)
            dst_vg = obj.vertex_groups.get(dst_name)
            if not src_vg or not dst_vg:
                continue
            src_idx = src_vg.index
            dst_idx = dst_vg.index
            touched = []
            for v in obj.data.vertices:
                src_w = 0.0
                dst_w = 0.0
                for g in v.groups:
                    if g.group == src_idx:
                        src_w = g.weight
                    elif g.group == dst_idx:
                        dst_w = g.weight
                if src_w <= 0.001:
                    continue
                dst_vg.add([v.index], min(1.0, dst_w + src_w), 'REPLACE')
                touched.append(v.index)
                modified += 1
            if touched:
                src_vg.remove(touched)
    return modified
