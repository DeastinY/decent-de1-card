"""Render the Decent DE1PRO CAD model for the card.

Run from this directory after `node convert.mjs` produced de1.json:

  PYTHONHOME=/usr blender -b --factory-startup --python-use-system-env --python scene.py -- \
    '{"samples":384,"w":1500,"h":1300,"out":"final/anchors.png","dist":1.6,"el":14,"key":50,
      "base_mat":"smoke","tank_mat":"acrylic","world":0.15,
      "levels":[0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0],"outdir":"final"}'

(PYTHONHOME is only needed when another Python on PATH confuses Blender.)
Writes final/level_XXX.png (one render per water level) and final/anchors.png.json
(tablet screen corners and tank position in image space).

The water is real liquid, not a coloured panel: a smooth 1.333 dielectric with a volume
that absorbs with depth, lit by its own small backlight inside the base so it reads through
the glass. Only the tank and the plinth shell wrapping it are that glass; the drip tray, the
legs and the feet keep their own materials. smoke_ior/tank_ior sit close to 1 on purpose:
at this grazing angle it is Fresnel, not tint, that turns a glass panel into a mirror, and
every dioptre of refraction between the camera and the fill smears the waterline. The rest
is tuned with smoke_color/smoke_rough, water_tint/water_density (how strongly the fill
colours), tank_light/_z/_h (the backlight) and water_rim (the bevel that gives the waterline
its highlight); "tray_mat":"smoke" additionally glasses the drip tray's pan, which uncovers
the right-hand half of the tank. "border": [x0,y0,x1,y1] renders just that crop, which is
the quick way to iterate on any of them.
"""
import bpy, json, bmesh, math, mathutils, sys, os
from mathutils import Vector
args = json.loads(sys.argv[sys.argv.index('--')+1]) if '--' in sys.argv else {}
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
data = json.load(open('de1.json'))

SKIP = ('Relay', 'PCB', 'Partition', 'Fuse', 'IEC', 'Uptake', 'Drain Path', 'Grommet', 'Barb', 'Guide Rod', 'Snap Clip', 'Nut Hex', 'Left Panel Bracket', 'Heat Isolation', 'M10 Panel', 'Chassis', 'Spacer, 4MM')
# ---------- materials
def principled(name, base, metal=0.0, rough=0.5, coat=0.0, aniso=0.0, trans=0.0, ior=1.45, emission=None, estr=0.0, alpha=1.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*base, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    b.inputs['Coat Weight'].default_value = coat
    b.inputs['Anisotropic'].default_value = aniso
    b.inputs['Transmission Weight'].default_value = trans
    b.inputs['IOR'].default_value = ior
    b.inputs['Alpha'].default_value = alpha
    if emission:
        b.inputs['Emission Color'].default_value = (*emission, 1); b.inputs['Emission Strength'].default_value = estr
    return m
def water_mat(name, tint, density, rough):
    """Clear liquid: a smooth 1.333 dielectric with a volume that tints with depth,
    so the fill reads as a body of water rather than a coloured pane."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (1, 1, 1, 1)
    b.inputs['Metallic'].default_value = 0.0
    b.inputs['Roughness'].default_value = rough
    b.inputs['Transmission Weight'].default_value = 1.0
    b.inputs['IOR'].default_value = 1.333
    va = nt.nodes.new('ShaderNodeVolumeAbsorption')
    va.inputs['Color'].default_value = (*tint, 1)
    va.inputs['Density'].default_value = density
    nt.links.new(va.outputs['Volume'], nt.nodes['Material Output'].inputs['Volume'])
    return m
M = {
 'body': principled('Body', (0.004,0.004,0.0045), rough=0.55, coat=0.08),
 'smoke': principled('Smoke', args.get('smoke_color',(0.72,0.75,0.78)), rough=args.get('smoke_rough',0.02), trans=1.0, ior=args.get('smoke_ior',1.03)),
 'acrylic': principled('Acrylic', args.get('tank_color',(0.9,0.95,1.0)), rough=args.get('tank_rough',0.01), trans=1.0, ior=args.get('tank_ior',1.06)),
 'water': water_mat('Water', tint=args.get('water_tint',(0.10,0.45,0.55)), density=args.get('water_density',45.0), rough=args.get('water_rough',0.0)),
 'black': principled('BlackPlastic', (0.012,0.012,0.013), rough=0.35),
 'rubber': principled('Rubber', (0.01,0.01,0.01), rough=0.8),
 'steel': principled('Steel', (0.78,0.78,0.79), metal=1, rough=0.16),
 'brushed': principled('Brushed', (0.56,0.56,0.57), metal=1, rough=0.34, aniso=0.6),
 'wood': principled('Wood', (0.23,0.11,0.045), rough=0.45, coat=0.4),
 'copper': principled('Copper', (0.8,0.45,0.25), metal=1, rough=0.25),
 'screen': principled('Screen', (0.005,0.005,0.006), rough=0.05, coat=1.0),
}
# 'Rubber Feet' comes first on purpose: the feet are named "... Rubber Feet, ZP25UN, Leg Base",
# so a Leg Base rule ahead of it would turn them into glass along with the plinth.
FORCE = {'Rubber Feet':'rubber','Main Cover':'body','Rear Face':'body','Water Tank':args.get('tank_mat','body'),'Group Head Controller':'body','Android Tablet':'black','Front Face Plate, Brushed':'brushed','Hanging spring':'black','USB':'black','Button LED':'steel'}
def classify(obj_name, color, span=None):
    n = obj_name
    for k,v in FORCE.items():
        if k in n: return v
    if 'Leg Base' in n:
        # the plinth is one part in the CAD: the wide shell wraps the tank and is what you
        # look through, the narrow uprights under it are the legs and stay metal
        wide = span is None or span > 0.15
        return args.get('base_mat','body') if wide else 'body'
    if color is None:
        if 'Main Cover' in n or 'Rear Face' in n: return 'body'
        if 'Portafilter' in n: return 'steel'
        if 'Button LED' in n: return 'steel'
        return 'black'
    r,g,b = color
    # the ribbed grate is always metal; the bucket under it is the case black. tray_mat can
    # make that bucket glass instead, which uncovers the right-hand half of the tank
    if 'Drip Tray' in n: return 'brushed' if max(r,g,b) > 0.4 else args.get('tray_mat','body')
    if abs(r-0.376)<.01 and abs(g-0.2307)<.01: return 'wood'
    if r > .7 and g < .5: return 'copper'
    if max(r,g,b) < 0.25 or b > .9 and r < .3: 
        if 'Rubber' in n: return 'rubber'
        return 'black'
    if 'Front Face Plate, Brushed' in n or 'Drip Tray' in n: return 'brushed'
    if 'Tank' in n: return 'black'
    return 'steel'

col = bpy.data.collections.new('DE1'); scene.collection.children.link(col)
groups = {}
for m in data:
    name = m['name'].split('/')[-1].strip()
    if any(s in name for s in SKIP): continue
    groups.setdefault(name, []).append(m)
objs = {}
for name, ms in groups.items():
    verts=[]; faces=[]; mats=[]; off=0; slot={}
    for m in ms:
        p=m['pos']; verts += [(p[i]/1000,p[i+1]/1000,p[i+2]/1000) for i in range(0,len(p),3)]
        xs = p[0::3]; span = (max(xs)-min(xs))/1000
        ix=m['idx']; ntri=len(ix)//3
        tri_mat=[classify(name, m['color'], span)]*ntri
        for f in m['brep_faces']:
            if f['color'] is not None:
                c=classify(name, f['color'], span)
                for t in range(f['first'], f['last']+1): tri_mat[t]=c
        faces += [(ix[i]+off,ix[i+1]+off,ix[i+2]+off) for i in range(0,len(ix),3)]
        mats += tri_mat
        off += len(p)//3
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces)
    keys = sorted(set(mats))
    for k in keys: me.materials.append(M[k])
    me.polygons.foreach_set('material_index', [keys.index(k) for k in mats])
    me.update()
    bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-5); bm.to_mesh(me); bm.free()
    me.shade_smooth_by_angle(angle=math.radians(30)) if hasattr(me,'shade_smooth_by_angle') else None
    ob = bpy.data.objects.new(name, me); col.objects.link(ob)
    ob.rotation_euler = (math.radians(90), 0, 0)  # CAD Y-up -> Blender Z-up, front (+Z) -> -Y
    objs[name] = ob
bpy.context.view_layer.update()
# smooth shading via modifier if needed
for ob in objs.values():
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
try:
    bpy.ops.object.shade_auto_smooth(angle=math.radians(30))
except Exception as e:
    print('autosmooth op failed', e)
for ob in objs.values(): ob.select_set(False)

# floor at the feet
zmin = min((ob.matrix_world @ Vector(c)).z for ob in objs.values() for c in ob.bound_box)
for ob in objs.values(): ob.location.z -= zmin
bpy.context.view_layer.update()

# ---------- tablet screen: faces of the tablet facing front/up with the biggest area
tab = objs['13041 ASSY DE1 Android Tablet']
me = tab.data
from collections import defaultdict
cands = [p for p in me.polygons if (tab.matrix_world.to_3x3() @ p.normal).y < -0.5]
# pick the plane furthest to the front along its normal
if cands:
    nrm = (tab.matrix_world.to_3x3() @ cands[0].normal).normalized()
    best = max(cands, key=lambda p: -(tab.matrix_world @ p.center).dot(nrm) * -1)
    dmax = max((tab.matrix_world @ p.center).dot(-(tab.matrix_world.to_3x3() @ p.normal).normalized()*-1) for p in cands)
if 'Screen' not in [m.name for m in me.materials]: me.materials.append(M['screen'])
si = [m.name for m in me.materials].index('Screen')
# largest coplanar front group
area = defaultdict(float); members = defaultdict(list)
for p in cands:
    n = (tab.matrix_world.to_3x3() @ p.normal).normalized()
    key = (round(n.x,2), round(n.y,2), round(n.z,2), round((tab.matrix_world @ p.center).dot(n),3))
    area[key] += p.area; members[key].append(p.index)
front_key = max(area, key=lambda k: area[k])
for i in members[front_key]: me.polygons[i].material_index = si
pts = [tab.matrix_world @ me.vertices[v].co for i in members[front_key] for v in me.polygons[i].vertices]
print('screen plane', front_key, 'area', area[front_key])

# ---------- shadow catcher
bpy.ops.mesh.primitive_plane_add(size=6, location=(0,0,0))
floor = bpy.context.active_object; floor.is_shadow_catcher = True

# ---------- lights (studio)
def area_light(name, loc, rot, size, energy, color=(1,1,1)):
    l = bpy.data.lights.new(name, 'AREA'); l.shape='RECTANGLE'; l.size=size[0]; l.size_y=size[1]; l.energy=energy; l.color=color
    o = bpy.data.objects.new(name, l); scene.collection.objects.link(o); o.location=loc
    d = Vector((0,0,0.2)) - Vector(loc); o.rotation_euler = d.to_track_quat('-Z','Y').to_euler()
    return o
area_light('Key',  (-0.9,-1.0,1.0), None, (0.9,0.9), args.get('key',60))
area_light('Fill', ( 1.1,-0.8,0.5), None, (1.2,0.6), args.get('fill',18))
area_light('Rim',  ( 0.6, 1.0,1.2), None, (0.4,1.2), args.get('rim',80))
area_light('Top',  ( 0.0, 0.0,1.6), None, (1.0,1.0), args.get('top',25))

def aimed_light(name, loc, look_at, size, energy, color=(1,1,1)):
    l = bpy.data.lights.new(name, 'AREA'); l.shape='RECTANGLE'; l.size=size[0]; l.size_y=size[1]
    l.energy=energy; l.color=color
    o = bpy.data.objects.new(name, l); scene.collection.objects.link(o); o.location=loc
    o.rotation_euler = (Vector(look_at)-Vector(loc)).to_track_quat('-Z','Y').to_euler()
    return o
world = bpy.data.worlds.new('W'); scene.world = world; world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Color'].default_value=(0.6,0.62,0.65,1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value=args.get('world',0.25)

# ---------- camera
cam_d = bpy.data.cameras.new('Cam'); cam_d.lens = args.get('lens', 70)
cam = bpy.data.objects.new('Cam', cam_d); scene.collection.objects.link(cam); scene.camera = cam
bbmin = Vector([min((ob.matrix_world @ Vector(c))[i] for ob in objs.values() for c in ob.bound_box) for i in range(3)])
bbmax = Vector([max((ob.matrix_world @ Vector(c))[i] for ob in objs.values() for c in ob.bound_box) for i in range(3)])
center = (bbmin+bbmax)/2
print('bbox', bbmin, bbmax)
az = math.radians(args.get('az', -38)); el = math.radians(args.get('el', 20)); dist = args.get('dist', 1.75)
target = Vector((center.x, center.y, center.z*args.get('tz',0.95)))
cam.location = target + Vector((math.sin(az)*math.cos(el), -math.cos(az)*math.cos(el), math.sin(el)))*dist
cam.rotation_euler = (target - cam.location).to_track_quat('-Z','Y').to_euler()

# ---------- water volume inside the tank
import bpy_extras
tank = objs['73741 DE1 Water Tank']
tb = [tank.matrix_world @ Vector(c) for c in tank.bound_box]
tmin = Vector([min(v[i] for v in tb) for i in range(3)]); tmax = Vector([max(v[i] for v in tb) for i in range(3)])
print('tank', tmin, tmax)
# A small light behind the tank, inside the base. Water in an unlit dark box is invisible;
# backlit, it glows and its surface throws a bright line, which is what makes a level read.
# Light linking keeps it off the smoked skirt, which would otherwise just wash out.
tank_lit = bpy.data.collections.new('TankLit'); tank_lit.objects.link(tank)
if args.get('tank_light', 25) > 0:
    tz = tmin.z + (tmax.z-tmin.z) * args.get('tank_light_z', 0.5)
    tl = aimed_light('Tank',
                     ((tmin.x+tmax.x)/2, tmax.y+0.02, tz),
                     ((tmin.x+tmax.x)/2, tmin.y, tz),
                     (tmax.x-tmin.x, (tmax.z-tmin.z)*args.get('tank_light_h', 0.8)),
                     args.get('tank_light', 25), tuple(args.get('tank_light_color', (0.80, 0.91, 1.0))))
    tl.light_linking.receiver_collection = tank_lit

INSET = 0.004                      # water stands clear of the tank wall, so the wall still reads
FLOOR = 0.006                      # the tank's moulded floor sits this far up
RIM = args.get('water_rim', 0.006)  # rounding on the top edge: this is what catches the light

def make_water():
    """A rounded slab of liquid inside the tank. The top edge is bevelled hard so the
    waterline picks up a specular rim instead of ending in a flat, graphic cut."""
    bpy.ops.mesh.primitive_cube_add(size=1)
    w = bpy.context.active_object; w.name = 'WaterVolume'
    w.data.materials.append(M['water'])
    bev = w.modifiers.new('bev', 'BEVEL')
    bev.width = RIM; bev.segments = 5; bev.limit_method = 'ANGLE'
    bev.harden_normals = True
    # assets.py keeps only what changes with the level, cropped to the tank, so the water
    # must not light or reflect into the rest of the frame. Shadow rays stay on: they are
    # what darkens the tank floor under the fill.
    w.visible_diffuse = w.visible_glossy = w.visible_volume_scatter = False
    tank_lit.objects.link(w)
    return w

def set_level(w, lv):
    """Fill to lv (0..1) of the usable tank depth."""
    w.hide_render = lv <= 0
    usable = tmax.z - tmin.z - FLOOR - INSET
    h = max(0.0012, usable * lv)
    w.scale = ((tmax.x-tmin.x-2*INSET), (tmax.y-tmin.y-2*INSET), h)
    w.location = ((tmin.x+tmax.x)/2, (tmin.y+tmax.y)/2, tmin.z+FLOOR+h/2)

level = args.get('level', None)
if level is not None and level > 0:
    set_level(make_water(), level)
# ---------- render settings
scene.render.engine = 'CYCLES'
prefs = bpy.context.preferences.addons['cycles'].preferences
for t in ('OPTIX','CUDA'):
    try:
        prefs.compute_device_type = t; prefs.get_devices(); 
        for d in prefs.devices: d.use = d.type != 'CPU'
        break
    except Exception as e: print('device', t, e)
scene.cycles.device = 'GPU'
scene.cycles.samples = args.get('samples', 256); scene.cycles.use_denoising = True
scene.render.film_transparent = True
scene.render.resolution_x = args.get('w', 1200); scene.render.resolution_y = args.get('h', 1000)
if args.get('border'):  # [x0,y0,x1,y1] in 0..1 image space: render just that crop, for quick looks
    bx0, by0, bx1, by1 = args['border']
    scene.render.use_border = True; scene.render.use_crop_to_border = True
    scene.render.border_min_x, scene.render.border_max_x = bx0, bx1
    scene.render.border_min_y, scene.render.border_max_y = 1-by1, 1-by0
scene.view_settings.view_transform = 'AgX'; scene.view_settings.look = 'AgX - Medium High Contrast'
scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = os.path.abspath(args.get('out','test.png'))
bpy.context.view_layer.update()
# ---------- projected anchors for the card overlay
def proj(v):
    co = bpy_extras.object_utils.world_to_camera_view(scene, cam, v)
    return [round(co.x,5), round(1-co.y,5)]
hull = pts
nrm_s = Vector(front_key[:3])
# screen corners: extremes along the plane's in-plane axes
ax_u = Vector((1,0,0)); ax_v = nrm_s.cross(ax_u).normalized()
us=[p.dot(ax_u) for p in hull]; vs=[p.dot(ax_v) for p in hull]
def pick(fu, fv): return max(hull, key=lambda p: fu*p.dot(ax_u)+fv*p.dot(ax_v))
corners = {'tl':pick(-1,1),'tr':pick(1,1),'br':pick(1,-1),'bl':pick(-1,-1)}
gh = objs['13022 ASSY DE1 Group Head_13022 - 110V Grouphead Assembly']
gb = [gh.matrix_world @ Vector(c) for c in gh.bound_box]
anchors = {'screen': {k: proj(v) for k,v in corners.items()},
           'tank_front_left': proj(Vector((tmin.x, tmin.y, (tmin.z+tmax.z)/2))),
           'tank_box': [proj(Vector((x,y,z))) for x in (tmin.x,tmax.x) for y in (tmin.y,tmax.y) for z in (tmin.z,tmax.z)],
           'group': proj(Vector(((min(v.x for v in gb)+max(v.x for v in gb))/2, min(v.y for v in gb)+0.03, min(v.z for v in gb))))}
json.dump(anchors, open(os.path.abspath(args.get('out','test.png'))+'.json','w'), indent=1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath('de1_scene.blend'))
scene.cycles.seed = 7
if args.get('levels'):
    w = make_water()
    for lv in args['levels']:
        set_level(w, lv)
        scene.render.filepath = os.path.abspath(f"{args['outdir']}/level_{int(round(lv*100)):03d}.png")
        bpy.ops.render.render(write_still=True)
elif args.get('render', True): bpy.ops.render.render(write_still=True)
