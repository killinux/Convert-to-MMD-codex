def create_hip_blend_zone(armature, mesh_objects, transition_height=1.5):
    """Create or repair the hip blend zone between thigh D-bones and lower body.

    The implementation is migrated from the legacy bone operator so later
    refactors can call this module directly without importing UI/operator code.
    """
    blend_pairs = [
        ("足D.L", "下半身", "左足"),
        ("足D.R", "下半身", "右足"),
    ]
    # 大腿顶部渐变带只保留很窄的一条，避免腿根主体被过度洗成“下半身”。
    # 目标是只平滑裆部顶端，而不是吞掉整段腿根。
    blend_top_frac = 0.08
    total_modified = 0

    for obj in mesh_objects:
        mw = obj.matrix_world

        for d_bone_name, shimono_name, fk_bone_name in blend_pairs:
            vg_d = obj.vertex_groups.get(d_bone_name)
            vg_s = obj.vertex_groups.get(shimono_name)
            if not vg_d or not vg_s:
                continue

            idx_d = vg_d.index
            idx_s = vg_s.index

            fk_bone = armature.data.bones.get(fk_bone_name)
            if not fk_bone:
                continue

            hip_z = (armature.matrix_world @ fk_bone.head_local).z
            knee_z = (armature.matrix_world @ fk_bone.tail_local).z
            hip_x = (armature.matrix_world @ fk_bone.head_local).x

            if abs(hip_z - knee_z) < 0.001:
                continue

            z_bottom = min(hip_z, knee_z)
            z_top = max(hip_z, knee_z)
            thigh_len = z_top - z_bottom

            opposite_d_name = "足D.R" if d_bone_name == "足D.L" else "足D.L"
            vg_opp = obj.vertex_groups.get(opposite_d_name)
            idx_opp = vg_opp.index if vg_opp else -1
            # Prefer the explicit transition height from UI/operator.
            # Fall back to the legacy thigh-length fraction so very small rigs
            # still get a visible blend strip instead of zero-width behavior.
            blend_height = min(thigh_len, max(0.05, transition_height))
            legacy_height = blend_top_frac * thigh_len
            effective_blend_height = min(thigh_len, min(blend_height, legacy_height))
            z_blend_threshold = z_top - effective_blend_height

            for v in obj.data.vertices:
                vz = (mw @ v.co).z
                if vz < z_blend_threshold or vz > z_top:
                    continue

                vx = (mw @ v.co).x
                if hip_x > 0 and vx < -0.02:
                    continue
                if hip_x < 0 and vx > 0.02:
                    continue

                if idx_opp >= 0:
                    wd_self = wd_opp = 0.0
                    for g in v.groups:
                        if g.group == idx_d:
                            wd_self = g.weight
                        if g.group == idx_opp:
                            wd_opp = g.weight
                    if wd_opp > wd_self + 0.01:
                        continue

                t = (z_top - vz) / effective_blend_height
                target_dr = t

                wd = ws = 0.0
                for g in v.groups:
                    if g.group == idx_d:
                        wd = g.weight
                    if g.group == idx_s:
                        ws = g.weight

                delta = target_dr - wd
                if abs(delta) < 0.0005:
                    continue

                if delta > 0:
                    transfer = min(ws, delta)
                    if transfer >= 0.0005:
                        vg_s.add([v.index], ws - transfer, 'REPLACE')
                        vg_d.add([v.index], wd + transfer, 'REPLACE')
                    elif delta >= 0.0005:
                        vg_d.add([v.index], target_dr, 'REPLACE')
                else:
                    transfer = -delta
                    vg_d.add([v.index], wd - transfer, 'REPLACE')
                    vg_s.add([v.index], ws + transfer, 'REPLACE')

                total_modified += 1

    for obj in mesh_objects:
        vg_dl = obj.vertex_groups.get("足D.L")
        vg_dr = obj.vertex_groups.get("足D.R")
        vg_fl = obj.vertex_groups.get("左足")
        vg_fr = obj.vertex_groups.get("右足")
        if not vg_dl or not vg_dr:
            continue

        idx_l = vg_dl.index
        idx_r = vg_dr.index
        idx_fl = vg_fl.index if vg_fl else -1
        idx_fr = vg_fr.index if vg_fr else -1

        mw = obj.matrix_world
        for v in obj.data.vertices:
            wl = wr = fl = fr = 0.0
            for g in v.groups:
                if g.group == idx_l:
                    wl = g.weight
                if g.group == idx_r:
                    wr = g.weight
                if g.group == idx_fl:
                    fl = g.weight
                if g.group == idx_fr:
                    fr = g.weight

            if wl < 0.001 and wr < 0.001:
                continue

            vx = (mw @ v.co).x
            if wl >= 0.001 and wr >= 0.001:
                if fl > fr * 2.0:
                    vg_dr.add([v.index], 0.0, 'REPLACE')
                    total_modified += 1
                elif fr > fl * 2.0:
                    vg_dl.add([v.index], 0.0, 'REPLACE')
                    total_modified += 1
                elif vx > 0.02:
                    vg_dr.add([v.index], 0.0, 'REPLACE')
                    total_modified += 1
                elif vx < -0.02:
                    vg_dl.add([v.index], 0.0, 'REPLACE')
                    total_modified += 1
                else:
                    combined = wl + wr
                    if combined > 1.01:
                        vg_dl.add([v.index], wl / combined, 'REPLACE')
                        vg_dr.add([v.index], wr / combined, 'REPLACE')
                        total_modified += 1
                continue

            if vx > 0.02 and wr >= 0.001:
                vg_dr.add([v.index], 0.0, 'REPLACE')
                total_modified += 1
            elif vx < -0.02 and wl >= 0.001:
                vg_dl.add([v.index], 0.0, 'REPLACE')
                total_modified += 1

    return total_modified
