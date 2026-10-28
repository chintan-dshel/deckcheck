"""Print what the extracted data says for each keyword behind M0's seven defects, beside the deck evidence."""
from deckcheck.keywords import load

CASES = [
    ("BOUNDARY_SPC_SET", "_ID option card placement (bolts001.key:78-81)"),
    ("CONTACT_DRAWBEAD", "_ID option + set types (cross_member_op10.dyn)"),
    ("CONTACT_AUTOMATIC_SINGLE_SURFACE_MORTAR", "ssid kind depends on sstyp (bolts001.key:288-291)"),
    ("CONTACT_AUTOMATIC_NODES_TO_SURFACE", "ssid/msid kind depends on sstyp/mstyp"),
    ("ICFD_PART", "defines ICFD part ids (tutorial 9 main_fsi)"),
    ("ICFD_PART_VOL", "references ICFD parts"),
    ("MESH_VOLUME", "references ICFD parts"),
    ("PART_INERTIA", "defines PART (torture part_inertia)"),
    ("PART", "heading then ids; blank heading line (torture blank_title)"),
    ("BOUNDARY_PRESCRIBED_MOTION_RIGID", "pid is a PART, not a NODE (EX09)"),
    ("CONTROL_IMPLICIT_SOLUTION", "arcctl = 0 means off (beam_sub.key:66)"),
    ("DEFINE_TABLE", "series lcid -> DEFINE_CURVE (crashbox.k:153339)"),
    ("AIRBAG_SIMPLE_PRESSURE_VOLUME", "negative cn = curve |cn| (BARRIER_DELAY_20MS.k:38195)"),
    ("INCLUDE_TRANSFORM", "tranid -> DEFINE_TRANSFORMATION (Yaris combine.key:101)"),
    ("RIGIDWALL_PLANAR", "nsid -> SET_NODE (Yaris combine.key:238)"),
    ("INITIAL_VELOCITY_GENERATION", "nsid/pid kind depends on styp (Yaris set-yaris:224)"),
]

data = load()["keywords"]
for name, why in CASES:
    k = data.get(name)
    print(f"\n== {name}: {why}")
    if k is None:
        print("   NOT IN DATA")
        continue
    print("   options:", [(o["name"], o["position"]) for o in k["options"]])
    print("   links:  ", k["links"])
    for c in k["cards"]:
        fields = [f["name"] for f in c.get("fields", [])] or [f["name"] for s in c.get("cards", []) for f in s["fields"]]
        print(f"   {c['kind']:<11} opt={c['option']!s:<6} cond={c['conditional']!s:<5} {fields[:10]}")
