"""Read-only Blender scene audit; invoke with --python and -- --output JSON.

Checks source meshes only, without evaluating modifiers or engine simulation.
Reports omit absolute input and image paths unless --include-paths is supplied.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
import bpy


def matrix(value):
    return [[float(c) for c in row] for row in value]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-influences', type=int, required=True)
    parser.add_argument('--include-paths', action='store_true',
                        help='Record absolute input and image paths (may expose local details)')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.max_influences < 1:
        raise ValueError('Positive influence limit required')
    output = args.output.resolve()
    if bpy.data.filepath and output == Path(bpy.data.filepath).resolve():
        raise ValueError('Audit output cannot overwrite the input blend')
    armatures, meshes = [], []
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE':
            armatures.append({'name': obj.name, 'matrix_world': matrix(obj.matrix_world),
                'bones': [{'name': b.name, 'parent': b.parent.name if b.parent else None,
                           'deform': b.use_deform, 'matrix_local': matrix(b.matrix_local)} for b in obj.data.bones]})
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        rigs = [m.object for m in obj.modifiers if m.type == 'ARMATURE' and m.object]
        deform = {b.name for rig in rigs for b in rig.data.bones if b.use_deform}
        group_names = {g.index: g.name for g in obj.vertex_groups}
        samples = {k: [] for k in ('unweighted', 'over_limit', 'not_normalized', 'invalid_weights')}
        totals = Counter()
        histogram = Counter()
        max_influences = 0
        for vertex in mesh.vertices:
            skin = [g.weight for g in vertex.groups if group_names.get(g.group) in deform]
            invalid = any(not math.isfinite(w) or w < 0 for w in skin)
            active = [w for w in skin if math.isfinite(w) and w > 1e-6]
            n = len(active)
            if rigs:
                histogram[n] += 1
                max_influences = max(max_influences, n)
                conditions = {'unweighted': n == 0, 'over_limit': n > args.max_influences,
                              'not_normalized': n > 0 and abs(sum(active) - 1) > 1e-4,
                              'invalid_weights': invalid}
                for key, bad in conditions.items():
                    if bad:
                        totals[key] += 1
                        if len(samples[key]) < 20:
                            samples[key].append(vertex.index)
        edge_faces = Counter(tuple(sorted(e)) for poly in mesh.polygons for e in poly.edge_keys)
        meshes.append({'name': obj.name, 'vertices': len(mesh.vertices), 'polygons': len(mesh.polygons),
            'triangles_if_triangulated': sum(max(0, len(p.vertices) - 2) for p in mesh.polygons),
            'ngons': sum(len(p.vertices) > 4 for p in mesh.polygons),
            'zero_area_faces': sum(p.area < 1e-12 for p in mesh.polygons),
            'boundary_edges': sum(n == 1 for n in edge_faces.values()),
            'edges_with_more_than_two_faces': sum(n > 2 for n in edge_faces.values()),
            'matrix_world': matrix(obj.matrix_world), 'uv_layers': [u.name for u in mesh.uv_layers],
            'materials': [s.material.name if s.material else None for s in obj.material_slots],
            'bad_material_face_indices': sum(p.material_index >= len(obj.material_slots) or
                obj.material_slots[p.material_index].material is None for p in mesh.polygons),
            'modifiers': [{'name': m.name, 'type': m.type} for m in obj.modifiers],
            'shape_keys': [k.name for k in mesh.shape_keys.key_blocks] if mesh.shape_keys else [],
            'armature_modifiers': [r.name for r in rigs], 'parent_type': obj.parent_type,
            'parent_bone': obj.parent_bone, 'max_deform_influences': max_influences,
            'influence_histogram': dict(histogram), 'weight_issue_counts': dict(totals),
            'weight_issue_samples': samples,
            'non_deform_groups': [g.name for g in obj.vertex_groups if g.name not in deform]})
    images = []
    for img in bpy.data.images:
        path = bpy.path.abspath(img.filepath, library=img.library) if img.filepath else ''
        packed = bool(img.packed_file) or bool(getattr(img, 'packed_files', []))
        report_path = path if args.include_paths else (Path(path).name if path else '')
        images.append({'name': img.name, 'source': img.source, 'size': list(img.size),
            'channels': img.channels, 'colorspace': img.colorspace_settings.name,
            'packed': packed, 'path': report_path,
            'missing_external_single_file': img.source == 'FILE' and not packed and
                (not path or not Path(path).is_file())})
    materials = []
    for mat in bpy.data.materials:
        nodes = mat.node_tree.nodes if mat.use_nodes and mat.node_tree else []
        materials.append({'name': mat.name, 'use_nodes': mat.use_nodes,
            'diffuse_color': list(mat.diffuse_color),
            'nodes': [{'name': n.name, 'type': n.type,
                       'image': n.image.name if n.type == 'TEX_IMAGE' and n.image else None}
                      for n in nodes]})
    input_path = bpy.data.filepath if args.include_paths else Path(bpy.data.filepath).name
    report = {'blender_version': bpy.app.version_string, 'input': input_path,
        'absolute_paths_included': args.include_paths,
        'scope': 'Unevaluated source mesh audit; material groups, UDIMs and runtime physics need separate inspection.',
        'unit_system': bpy.context.scene.unit_settings.system,
        'unit_scale': bpy.context.scene.unit_settings.scale_length,
        'armatures': armatures, 'meshes': meshes, 'materials': materials, 'images': images}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('AUDIT_WRITTEN', output, 'meshes', len(meshes), 'armatures', len(armatures))


if __name__ == '__main__':
    main()
